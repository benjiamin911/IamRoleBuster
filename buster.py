#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

import botocore
import botocore.exceptions
import random
import string

import typing

import json
import boto3
from copy import deepcopy

if typing.TYPE_CHECKING:
    import mypy_boto3_iam
    import mypy_boto3_iam.type_defs

module_info = {
    'name': 'iam__enum_roles',
    'category': 'RECON_UNAUTH',
    'one_liner': 'Enumerates IAM roles in a separate AWS account, given the account ID.',
    'description': (
        'This module takes in a valid AWS account ID and tries to enumerate existing IAM roles within that account. It does '
        'so by trying to update the AssumeRole policy document of the role that you pass into --role-name if passed or newly'
        'created role. NOTE: It is recommended to use personal AWS access '
        'keys for this script, as it will spam CloudTrail with "iam:UpdateAssumeRolePolicy" logs and a few "sts:AssumeRole" '
        'logs. The target account will not see anything in their logs though, unless you find a misconfigured role that '
        'allows you to assume it. The keys used must have the iam:UpdateAssumeRolePolicy permission on the role that you '
        'pass into --role-name to be able to identify a valid IAM role and the sts:AssumeRole permission to try and request '
        'credentials for any enumerated roles.'
    ),
    'services': ['IAM', 'STS'],
    'prerequisite_modules': [],
    'external_dependencies': [],
    'arguments_to_autocomplete': ['--word-list', '--role-name', '--account-id']
}

chars = string.ascii_lowercase + string.ascii_uppercase + string.digits

def run(args, role_name, iam):
    if not len(args.account_id) == 12 or not args.account_id.isdigit():
        print('Error: An AWS account ID is a number of length 12. You supplied: {}\n'.format(args.account_id))
        return None

    if args.word_list is None:
        word_list_path = f'{Path(__file__).parent}/default-word-list.txt'
    else:
        word_list_path = args.word_list.strip()

    with open(word_list_path, 'r') as f:
        word_list = f.read().splitlines()

    print(
        'Warning: This script does not check if the keys you supplied have the correct permissions. Make sure they are '
        'allowed to use iam:UpdateAssumeRolePolicy on the role that you pass into --role-name and are allowed to use '
        'sts:AssumeRole to try and assume any enumerated roles!\n'
    )

    data = {
        'attempts': 0,
        'valid_roles': [],
        'roles_assumed': []
    }

    print('Targeting account ID: {}\n'.format(args.account_id))
    print('Starting role enumeration...\n')
    for word in word_list:
        sys.stderr.write('.')
        role_arn = 'arn:aws:iam::{}:role/{}'.format(args.account_id, word)

        data['attempts'] += 1

        try:
            iam.update_assume_role_policy(
                RoleName=role_name,
                PolicyDocument='''
                {{
                    "Version":"2012-10-17",
                    "Statement":[{{
                        "Effect":"Deny",
                        "Principal":{{"AWS":"{}"}},
                        "Action":"sts:AssumeRole"
                    }}]
                }}'''.format(role_arn).strip()
            )
            print('\n  Found role: {}'.format(role_arn))
            data['valid_roles'].append(role_arn)
        except botocore.exceptions.ClientError as error:
            if 'MalformedPolicyDocument' in str(error):
                # Role doesn't exist, continue on
                pass
            elif 'NoSuchEntity' in str(error):
                print('  Error: You did not pass in a valid role name. An existing role is required for this script.')
                return data
            else:
                print('  Unhandled error: {}'.format(str(error)))
                raise error

    if len(data['valid_roles']) > 0:
        print('\nFound {} role(s):\n'.format(len(data['valid_roles'])))
        for role in data['valid_roles']:
            print('    {}'.format(role))
        print()


def main(args):
    session = boto3.Session(profile_name=args.profile)

    iam = session.client('iam')

    if args.role_name:
        role_name = args.role_name.split('/')[-1]  # Handle ARN's if that was passed for whatever reason.
        resp = iam.get_role(RoleName=role_name)
        orig_trust_doc = json.dumps(resp['Role']['AssumeRolePolicyDocument'])
    else:
        role_name = f"IamEnumRoles-{''.join(random.choice(chars) for _ in range(5))}"
        iam.create_role(
            RoleName=role_name,
            Description="Created for IAM Role enumeration.",
            AssumeRolePolicyDocument='''
            {
                "Version": "2012-10-17",
                "Statement": [{
                    "Effect": "Deny",
                    "Principal": {"AWS": "*"},
                    "Action": "sts:AssumeRole"
                }]
            }
            '''.strip(),
        )

    try:
        run(args, role_name, iam)
    except Exception as e:
        raise e
    finally:
        if args.role_name:
            print(f"Reverting the {role_name} trust policy.")
            try:
                iam.update_assume_role_policy(RoleName=role_name, PolicyDocument=orig_trust_doc)
            except Exception as err:
                print(f"unable to revert {role_name} to it's original state. this can be done manually by updating the assume"
                      f"role document to the following: \n\n{orig_trust_doc}\n\n")
                print(err)
        else:
            print(f"Cleaning up the {role_name} role.")
            iam.delete_role(RoleName=role_name)

if __name__ == "__main__":        
    parser = argparse.ArgumentParser(description=module_info['description'])
    parser.add_argument('--profile', required=False, default="default",
                        help='AWS profile to check the IAM Role.')
    parser.add_argument('--word-list', required=False, default="./default-word-list.txt",
                        help='File path to a different word list to use. The word list should contain words,'
                         'one on each line, to use to try and guess IAM role names. Role names ARE '
                            'case-sensitive.')
    parser.add_argument('--role-name', required=False,
                        help='The name of a valid role in the current users account to try and update the AssumeRole policy '
                            'document for. If this isn\'t specified a temporary role will be created')
    parser.add_argument('--account-id', required=True, help='The AWS account ID of the target account (12 numeric characters).')
    args = parser.parse_args()

    main(args)