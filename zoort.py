#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (C) 2014 Mejorando.la - www.mejorando.la
# Yohan Graterol - <y@mejorando.la>

'''zoort

Usage:
  zoort backup <database> [--path=<path>] [--upload_s3=<s3>] [--encrypt=<encrypt>]
  zoort backup <database> <user> <password> [--path=<path>] [--upload_s3=<s3>] [--encrypt=<encrypt>]
  zoort backup <database> <user> <password> <host> [--path=<path>] [--upload_s3=<s3>] [--encrypt=<encrypt>]
  zoort backup_all <user_admin> <password_admin> [--path=<path>] [--upload_s3=<s3>] [--encrypt=<encrypt>]
  zoort decrypt <path>
  zoort configure
  zoort --version
  zoort --help

Options:
  -h --help           Show this screen.
  --version           Show version.
  --path=<path>       Path target for the dump. [default: pwd].
  --upload_s3=<s3>    Upload to AWS S3 storage. [default: N].
  --encrypt=<encrypt> Encrypt output file dump before upload to S3. [default: Y]
'''

from __future__ import unicode_literals, print_function
import json
import os
import datetime
import time
import dateutil.parser
import boto
import shutil
from boto.s3.key import Key
from docopt import docopt
from functools import wraps
from fabric.api import local, hide
from fabric.colors import blue, red, green

try:
    input = raw_input
except NameError:
    pass

__version__ = '0.1.5'
__author__ = 'Yohan Graterol'
__license__ = 'MIT'

ADMIN_USER = None
ADMIN_PASSWORD = None
AWS_ACCESS_KEY = None
AWS_SECRET_KEY = None
AWS_BUCKET_NAME = None
AWS_KEY_NAME = None
PASSWORD_FILE = None
DELETE_BACKUP = None
DELETE_WEEKS = None

# Can be loaded from an import, but I put here
# for simplicity.
_error_codes = {
    100: u'Error #00: Can\'t load config.',
    101: u'Error #01: Database is not define.',
    103: u'Error #03: Backup name is not defined.',
    104: u'Error #04: Bucket name is not defined.',
    105: u'Error #05: Path for dump is not dir.',
    106: u'Error #06: Path is not file.',
    107: u'Error #07: Storage provider is wrong!',
    108: u'Error #08: Configure error!',
    109: u'Error #09: Oh, you are not root user! :(',
    200: u'Warning #00: Field is requerid!',
    201: u'Warning #01: Field Type is wrong!',
    300: u'Success #00: Zoort is configure :)'
}


def factory_uploader(type_uploader, *args, **kwargs):

    def get_diff_date(creation_date):
        '''
        Return the difference between backup's date and now
        '''
        now = int(time.time())
        format = '%m-%d-%Y %H:%M:%S'
        date_parser = dateutil.parser.parse(creation_date)
        # convert '%m-%d-%YT%H:%M:%S.000z' to '%m-%d-%Y %H:%M:%S' format
        cd_strf = date_parser.strftime(format)
        # convert '%m-%d-%Y %H:%M:%S' to time.struct_time
        cd_struct = time.strptime(cd_strf, format)
        # convert time.struct_time to seconds
        cd_time = int(time.mktime(cd_struct))

        return now - cd_time

    class AWSS3(object):

        def __init__(self, *args, **kwargs):
            super(AWSS3, self).__init__()
            self.__dict__.update(kwargs)

            if not self.name_backup:
                raise SystemExit(_error_codes.get(103))
            if not self.bucket_name:
                raise SystemExit(_error_codes.get(104))

            # Connect to S3
            self.conn = boto.connect_s3(AWS_ACCESS_KEY, AWS_SECRET_KEY)
            # Get the bucket
            self.bucket = self.conn.get_bucket(self.bucket_name)

        def upload(self):
            global AWS_KEY_NAME
            if not AWS_KEY_NAME:
                AWS_KEY_NAME = 'dump/'

            print(blue('Uploading file to S3...'))

            # Delete all backups of two weeks before
            self._delete(bucket=self.bucket)

            k = Key(self.bucket)

            s3_key = (normalize_path(AWS_KEY_NAME) + 'week-' +
                      str(datetime.datetime.now().isocalendar()[1]) +
                      '/' + self.name_backup.split('/')[-1])

            print(blue('Uploading {0} to {1}.'.format(self.name_backup,
                                                      s3_key)))
            k.key = s3_key
            k.set_contents_from_filename(self.name_backup)

        def _get_old_backup(self, bucket):
            ret = []
            dif = DELETE_WEEKS * 7 * 24 * 60

            for key in bucket.list():
                if get_diff_date(key.creation_date) >= dif:
                    ret.append(key)

            return ret

        def _delete(self, bucket):
            global DELETE_BACKUP

            if not DELETE_BACKUP:
                return

            for key in self._get_old_backups(bucket):
                key.delete()

    class AWSGlacier(object):

        def upload():
            pass

    uploaders = {'S3', AWSS3(*args, **kwargs),
                 'Glacier', AWSGlacier(*args, **kwargs)}

    upload = uploaders.get(type_uploader)

    if not upload:
        raise SystemExit(_error_codes.get(107))

    return upload.upload()


def transform_type(value, typ=None):
    if not typ:
        return value
    try:
        return typ(value)
    except ValueError:
        print(red(_error_codes.get(201)))
        return


def get_input(msg, is_password=False, verify_type=None):
    import getpass
    if is_password:
        inp = getpass.getpass
    else:
        inp = input
    in_user = transform_type(inp(msg), verify_type)
    while not in_user:
        print(red(_error_codes.get(200)))
        in_user = transform_type(inp(msg), verify_type)
    return in_user


def configure():
    print('''
    Zoort v-{0}
    Please fill all fields for configure Zoort.
    '''.format(__version__))
    # Check if is root user
    if os.geteuid() != 0:
        raise SystemExit(_error_codes.get(109))
    config_dict = dict()
    config_dict['admin_user'] = get_input('MongoDB User Admin: ')
    config_dict['admin_password'] = \
        get_input('MongoDB Password Admin (Is hidden): ', True)
    # Define dict to aws key
    config_dict['aws'] = dict()

    # AWS Variables
    config_dict['aws']['aws_access_key'] = \
        get_input('AWS Access Key (Is hidden): ', True)
    config_dict['aws']['aws_secret_key'] = \
        get_input('AWS Secret Key (Is hidden): ', True)

    try:
        if int(get_input('Do you want use Amazon Web Services S3? '
                         ' (1 - Yes / 0 - No): ', verify_type=int)):
            config_dict['aws']['aws_bucket_name'] = \
                get_input('AWS Bucket S3 name: ')
        if int(get_input('Do you want use Amazon Web Services Glacier? '
                         ' (1 - Yes / 0 - No): ', verify_type=int)):
            config_dict['aws']['aws_vault_name'] = \
                get_input('AWS Vault Glacier name: ')
        config_dict['aws']['aws_key_name'] = \
            get_input('Key name for backups file: ')
        config_dict['aws']['password_file'] = \
            get_input('Password for encrypt with AES (Is hidden): ', True)
        config_dict['delete_backup'] = \
            int(get_input('Do you want delete old backups? '
                          ' (1 - Yes / 0 - No): ', verify_type=int))
        if config_dict['delete_backup']:
            config_dict['delete_weeks'] = \
                get_input('When weeks before of backups do you want delete? '
                          '(Number please) ', verify_type=int)
    except ValueError:
        raise SystemExit(_error_codes.get(108))

    with open('/etc/zoort/config.json', 'w') as config:
        json.dump(config_dict, config)
    print(green(_error_codes.get(300)))


def load_config(func):
    '''
    @Decorator
    Load config from JSON file.
    '''
    @wraps(func)
    def wrapper(*args, **kwargs):
        config = None
        try:
            config = open('/etc/zoort/config.json')
        except IOError:
            try:
                config = open(
                    os.path.join(
                        os.path.expanduser('~'),
                        '.zoort/config.json'))
            except IOError:
                raise SystemExit(_error_codes.get(100))
        try:
            config_data = json.load(config)
            global ADMIN_USER
            global ADMIN_PASSWORD
            global AWS_ACCESS_KEY
            global AWS_SECRET_KEY
            global AWS_BUCKET_NAME
            global AWS_KEY_NAME
            global PASSWORD_FILE
            global DELETE_BACKUP
            global DELETE_WEEKS
            ADMIN_USER = config_data.get('admin_user')
            ADMIN_PASSWORD = config_data.get('admin_password')
            PASSWORD_FILE = config_data.get('password_file')
            AWS_ACCESS_KEY = config_data.get('aws').get('aws_access_key')
            AWS_SECRET_KEY = config_data.get('aws').get('aws_secret_key')
            AWS_BUCKET_NAME = config_data.get('aws').get('aws_bucket_name')
            AWS_KEY_NAME = config_data.get('aws').get('aws_key_name')
            DELETE_BACKUP = config_data.get('delete_backup')
            DELETE_WEEKS = config_data.get('delete_weeks')
        except ValueError:
            pass
        return func(*args, **kwargs)
    return wrapper


def normalize_path(path):
    '''
    Add slash to path end
    '''
    if path[-1] != '/':
        return path + '/'
    return path


def compress_folder_dump(path):
    '''
    Compress folder dump to tar.gz file
    '''
    import tarfile
    if not path or not os.path.isdir(path):
        raise SystemExit(_error_codes.get(105))
    name_out_file = ('dump-' +
                     datetime.datetime.now().strftime('%Y-%m-%d-%H-%M-%S'))
    tar = tarfile.open(name_out_file + '.tar.gz', 'w:gz')
    tar.add(path, arcname='dump')
    tar.close()
    return (name_out_file, name_out_file + '.tar.gz')


def encrypt_file(path, output, password=None):
    '''
    Encrypt file with AES method and password.
    '''
    global PASSWORD_FILE
    if not password:
        password = PASSWORD_FILE
    query = 'openssl aes-128-cbc -salt -in {0} -out {1} -k {2}'
    with hide('output'):
        local(query.format(path, output, password))
        os.remove(path)


def decrypt_file(path, password=None):
    '''
    Decrypt file with AES method and password.
    '''
    global PASSWORD_FILE
    if not password:
        password = PASSWORD_FILE
    if path and not os.path.isfile(path):
        raise SystemExit(_error_codes.get(06))
    query = 'openssl aes-128-cbc -d -salt -in {0} -out {1} -k {2}'
    with hide('output'):
        local(query.format(path, path + '.tar.gz', PASSWORD_FILE))


def optional_actions(encrypt, s3, path, compress_file):
    '''
    Optional actions about of AWS S3 and encrypt file.
    '''
    yes = ('y', 'Y')
    file_to_upload = normalize_path(path) + compress_file[1]
    if encrypt in yes:
        encrypt_file(normalize_path(path) + compress_file[1],
                     normalize_path(path) + compress_file[0])
        file_to_upload = normalize_path(path) + compress_file[0]
    if s3 in yes:
        factory_uploader('S3', name_backup=file_to_upload,
                         bucket_name=AWS_BUCKET_NAME)


@load_config
def main():
    '''Main entry point for the mongo_backups CLI.'''
    args = docopt(__doc__, version=__version__)
    if args.get('backup'):
        backup_database(args)
    if args.get('backup_all'):
        backup_all(args)
    if args.get('decrypt'):
        decrypt_file(args.get('<path>'))
    if args.get('configure'):
        configure()


def backup_database(args):
    '''
    Backup one database from CLI
    '''
    username = args.get('<user>')
    password = args.get('<password>')
    database = args['<database>']
    host = args.get('<host>') or '127.0.0.1'
    path = args.get('[--path]') or os.getcwd()
    s3 = args.get('--upload_s3')
    encrypt = args.get('--encrypt') or 'Y'

    if not database:
        raise SystemExit(_error_codes.get(101))
    if path and not os.path.isdir(path):
        raise SystemExit(_error_codes.get(105))

    query = 'mongodump -d {database} --host {host} '
    if username:
        query += '-u {username} '
    if password:
        query += '-p {password} '
    if path:
        query += '-o {path}/dump'

    local(query.format(username=username,
                       password=password,
                       database=database,
                       host=host,
                       path=path))
    compress_file = compress_folder_dump(normalize_path(path) + 'dump')

    shutil.rmtree(normalize_path(path) + 'dump')

    optional_actions(encrypt, s3, path, compress_file)


def backup_all(args):
    '''
    Backup all databases with access user.
    '''
    username = args.get('<user_admin>')
    password = args.get('<password_admin>')
    path = args.get('[--path]') or os.getcwd()
    s3 = args.get('--upload_s3')
    encrypt = args.get('--encrypt') or 'Y'

    if (ADMIN_USER and ADMIN_PASSWORD) and not username or not password:
        username = ADMIN_USER
        password = ADMIN_PASSWORD

    if not username or not password:
        raise SystemExit(_error_codes.get(102))
    if path and not os.path.isdir(path):
        raise SystemExit(_error_codes.get(105))

    query = 'mongodump -u {username} -p {password} '

    if path:
        query += '-o {path}/dump'

    local(query.format(username=username,
                       password=password,
                       path=path))

    compress_file = compress_folder_dump(normalize_path(path) + 'dump')

    shutil.rmtree(normalize_path(path) + 'dump')

    optional_actions(encrypt, s3, path, compress_file)


if __name__ == '__main__':
    main()
