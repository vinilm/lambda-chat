#!/usr/bin/python
"""
Script to generate a CloudFormation Template that brings up all of the AWS
resources needed to run lambda-chat

This requires Python 2.7. To get the required libraries:
  sudo pip install docopt boto troposphere awacs pyyaml --upgrade

Usage:
  resources.py cf
  resources.py launch --region=<region>
  resources.py update --region=<region>
  resources.py delete --region=<region>
  resources.py output --region=<region>

Options:
  -h --help             Show this screen.
  --version             Show version.
  --region=<region>     The AWS region to use

License:
  Copyright 2015 CloudNative, Inc.
    https://cloudnative.io/

  Licensed under the Apache License, Version 2.0 (the "License");
  you may not use this file except in compliance with the License.
  You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

  Unless required by applicable law or agreed to in writing, software
  distributed under the License is distributed on an "AS IS" BASIS,
  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
  See the License for the specific language governing permissions and
  limitations under the License.

"""

# Import all the goodness
import sys
from docopt import docopt
import yaml
from boto import cloudformation
from troposphere import Template, Parameter, Output
from troposphere import Base64, FindInMap, GetAtt, GetAZs, Join, Ref, Select, Tags
import troposphere.ec2 as ec2
import troposphere.autoscaling as asg
import troposphere.iam as iam
import troposphere.sns as sns
from awacs.aws import Action, Allow, Policy, Statement, Principal, Condition, StringEquals


def default_config():
    """Returns a dict with the default configuration
    """
    return {
        'stack_name': 'Lambda-Chat',
        'tags': {
            'Name': 'Lambda Chat',
            'Creator': 'CloudNative'
        }
    }


def load_config():
    """Returns the default config merged with the what is in the config.yml file
    """
    try:
        # Attempt to load configuration file
        stream = file('config.yml', 'r');
        config = yaml.load(stream)
        config['loaded'] = True
    except IOError, e:
        config = {}
        config['loaded'] = False

    # Merge with default
    return dict(default_config().items() + config.items())


def assert_config_loaded():
    """Stops execution and displays an error message if the settings have not
    been loaded from config.yml
    """
    if not config['loaded']:
        print 'ERROR: Could not load file: config.yml'
        sys.exit(1)


def cf_params():
    """Returns the parameters needed to create or update the CloudFormation
    stack
    """
    assert_config_loaded()
    return [
        ('GoogleOAuthClientID', config['google_oauth_client_id']),
    ]


def generate_cf_template():
    """Returns an entire CloudFormation stack by using troposphere to construct
    each piece
    """
    # Header of CloudFormation template
    t = Template()
    t.add_version("2010-09-09")
    t.add_description("Lambda Chat AWS Resources")


    # Paramters
    google_oauth_client_id = t.add_parameter(Parameter(
        "GoogleOAuthClientID",
        AllowedPattern="[0-9]+-[a-z0-9]+.apps.googleusercontent.com",
        Type="String",
        Description="The Client ID of your Google project",
        ConstraintDescription="should match [0-9]+-[a-z0-9]+.apps.googleusercontent.com",
    ))

    # s3_bucket_name = t.add_parameter(Parameter(
    #     "S3BucketName",
    #     AllowedPattern="[a-zA-Z0-9\-]*",
    #     Type="String",
    #     Description="Name of S3 bucket to run the website from",
    #     ConstraintDescription="can contain only alphanumeric characters and dashes.",
    # ))


    # The SNS topic the website will publish chat messages to
    website_sns_topic = t.add_resource(sns.Topic(
        'WebsiteSnsTopic',
        TopicName='lambda-chat',
        DisplayName='Lambda Chat'
    ))
    output_website_sns_topic = t.add_output(Output(
        "WebsiteSnsTopic",
        Description="website_sns_topic_arn",
        Value=Ref(website_sns_topic),
    ))

    # The IAM Role and Policy the website will assume to publish to SNS
    website_role = t.add_resource(iam.Role(
        "WebsiteRole",
        Path="/",
        AssumeRolePolicyDocument=Policy(
            Statement=[
                Statement(
                    Effect=Allow,
                    Action=[Action("sts", "AssumeRoleWithWebIdentity")],
                    Principal=Principal("Federated", "accounts.google.com"),
                    Condition=Condition(
                        StringEquals(
                            "accounts.google.com:aud",
                            Ref(google_oauth_client_id)
                        )
                    ),
                ),
            ],
        ),
    ))
    website_policy = t.add_resource(iam.PolicyType(
        "WebsitePolicy",
        PolicyName="lambda-chat-website-policy",
        Roles=[Ref(website_role)],
        PolicyDocument=Policy(
            Version="2012-10-17",
            Statement=[
                Statement(
                    Effect=Allow,
                    Action=[Action("sns", "Publish")],
                    Resource=[
                        Ref(website_sns_topic)
                    ],
                ),
            ],
        )
    ));
    output_website_role = t.add_output(Output(
        "WebsiteRole",
        Description="website_iam_role_arn",
        Value=GetAtt(website_role, "Arn"),
    ))

    return t


def launch(args, config, cf_conn, template):
    """Create new CloudFormation Stack from the template
    """
    print "Creating CloudFormation Stack %s..." % config['stack_name']
    stack_id = cf_conn.create_stack(
      config['stack_name'],
      template_body=template.to_json(),
      parameters=cf_params(),
      tags=config['tags'],
      capabilities=['CAPABILITY_IAM']
    )
    print 'Created ' + stack_id


def update(args, config, cf_conn, template):
    """Update an existing CloudFormation Stack
    """
    print "Updating CloudFormation Stack %s..." % config['stack_name']
    stack_id = cf_conn.update_stack(
      config['stack_name'],
      template_body=template.to_json(),
      parameters=cf_params(),
      tags=config['tags'],
      capabilities=['CAPABILITY_IAM']
    )
    print 'Updated ' + stack_id


def delete(args, config, cf_conn):
    """Deletes an existing CloudFormation Stack
    """
    # Delete an existing CloudFormation Stack with same name
    print "Deleting CloudFormation Stack %s..." % config['stack_name']
    resp = cf_conn.delete_stack(
      config['stack_name'],
    )
    print resp


if __name__ == '__main__':
    args = docopt(__doc__, version='Lambda Chat AWS Resources 0.2')
    print(args)
    config = load_config();
    print(config)

    print_cf_template = args['cf'] or args['launch']

    try:
        if print_cf_template:
            template = generate_cf_template()
            print template.to_json();
            if (args['cf']):
                sys.exit(1)

        # Get a connection to AWS CloudFormation in the given region
        conn = cloudformation.connect_to_region(args['--region'])


        if (args['launch']):
            launch(args, config, conn, template)

        elif (args['update']):
            update(args, config, conn, template)

        elif (args['delete']):
            delete(args, config, conn)

        elif (args['output']):
            # Describe an existing CloudFormation Stack
            print "Deleting CloudFormation Stack..."
            resp = conn.describe_stacks(
              stack_name,
            )
            print resp

    except Exception, e:
        print 'ERROR'
        print e
        print e.message
