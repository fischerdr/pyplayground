#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""This is a script to migrate the configuration from one AWX instance to another.

This script is based on the original script by Serge van Ginderachter <serge@vanginderachter.be>
and the tower-cli project.

# Copyright 2018 Serge van Ginderachter <serge@vanginderachter.be>
# Copyright Ansible AWX and tower-cli contributors
# Licensed under the Apache License, Version 2.0
"""

import base64
import copy
import datetime
import hashlib
import json
import os
import pickle
import sys

import psycopg2
import psycopg2.extras
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.backends import default_backend
from tower_cli.cli.transfer.receive import Receiver

# default vales as per openshift deploy of AWX
AWX_SRC_SECRET_KEY = os.getenv("AWX_SRC_SECRET_KEY", "awxsecret")
AWX_SRC_DBNAME = os.getenv("AWX_SRC_DBNAME", "awx")
AWX_SRC_DBUSER = os.getenv("AWX_SRC_DBUSER", "awx")
AWX_SRC_DBPASSWORD = os.getenv("AWX_SRC_DBPASSWORD", "awxpass")
AWX_SRC_DBHOST = os.getenv("AWX_SRC_DBHOST", "localhost")
AWX_SRC_DBPORT = os.getenv("AWX_SRC_DBPORT", "5432")

AWX_DST_SECRET_KEY = os.getenv("AWX_DST_SECRET_KEY", "awxsecret")
AWX_DST_DBNAME = os.getenv("AWX_DST_DBNAME", "awx")
AWX_DST_DBUSER = os.getenv("AWX_DST_DBUSER", "awx")
AWX_DST_DBPASSWORD = os.getenv("AWX_DST_DBPASSWORD", "awxpass")
AWX_DST_DBHOST = os.getenv("AWX_DST_DBHOST", "localhost")
AWX_DST_DBPORT = os.getenv("AWX_DST_DBPORT", "5433")

AWX_SRC_DATA_CACHE = os.getenv("AWX_SRC_DATA_CACHE", "awx-data.pickle")


class Fernet256(Fernet):
    """Not techincally Fernet, but uses the base of the Fernet spec and uses AES-256-CBC instead of AES-128-CBC. All other functionality remain identical.

    Args:
        key: The key to use for encryption and decryption.
        backend: The backend to use for encryption and decryption.
    """

    def __init__(self, key, backend=None):
        """Initialize the Fernet256 class.

        Args:
            key: The key to use for encryption and decryption.
            backend: The backend to use for encryption and decryption.
        """
        if backend is None:
            backend = default_backend()

        key = base64.urlsafe_b64decode(key)
        if len(key) != 64:
            raise ValueError("Fernet key must be 64 url-safe base64-encoded bytes.")

        self._signing_key = key[:32]
        self._encryption_key = key[32:]
        self._backend = backend


def get_encryption_key(field_name, pk=None):
    """Generate key for encrypted password based on field name,``settings.SECRET_KEY``, and instance pk (if available).

    Args:
        field_name: The name of the field to encrypt.
        pk: The primary key of the model object.

    Returns:
        The encryption key.
    """
    h = hashlib.sha512()
    h.update(AWX_SRC_SECRET_KEY)
    if pk is not None:
        h.update(str(pk))
    h.update(field_name)
    return base64.urlsafe_b64encode(h.digest())


def decrypt_value(encryption_key, value):
    """Decrypt a single value, with it's specific encryption key.

    Args:
        encryption_key: The encryption key.
        value: The value to decrypt.

    Returns:
        The decrypted value.
    """
    raw_data = value[len("$encrypted$") :]

    # If the encrypted string contains a UTF8 marker, discard it
    utf8 = raw_data.startswith("UTF8$")
    if utf8:
        raw_data = raw_data[len("UTF8$") :]
    algo, b64data = raw_data.split("$", 1)
    if algo != "AESCBC":
        raise ValueError("unsupported algorithm: %s" % algo)
    encrypted = base64.b64decode(b64data)
    f = Fernet256(encryption_key)
    value = f.decrypt(encrypted)

    # If the encrypted string contained a UTF8 marker, decode the data
    if utf8:
        value = value.decode("utf-8")
    return value


def awx_get_data():
    """Get awx data from cache file is available, otherwise export it with tower-cli and save it in the cached file.

    Returns:
        The awx data.
    """
    if os.path.isfile(AWX_SRC_DATA_CACHE) and os.access(AWX_SRC_DATA_CACHE, os.W_OK):
        awx_data = pickle.load(open(AWX_SRC_DATA_CACHE, "rb"))
    else:
        awx_data = _awx_get_data()
        _awx_dump_data(awx_data)

    # data fixes, cleanup, bugs
    for item in awx_data:

        # Bug in awx 1.0.8
        # https://github.com/ansible/tower-cli/pull/586#issuecomment-432176155
        # remove objects that only contain
        # {
        #   "asset_type": "user"
        # },
        # which make `tower-cli send` complains:
        if item and item.get("asset_type") == "user" and len(item) == 1:
            # 'Asset of type user is missing identifier field username'
            awx_data.remove(item)

    return awx_data


def _awx_get_data():
    """Get awx data export from tower_cli.

    Returns:
        The awx data export.
    """
    receiver = Receiver()
    data = receiver.export_assets(all=True, asset_input=None)

    return data


def _awx_dump_data(data):
    """Write awx_data to cache file.

    Args:
        data: The awx data to dump.
    """
    pickle.dump(data, open(AWX_SRC_DATA_CACHE, "wb"))


def awx_getdb_creds():
    """Get the credentials from the database and store it in a dictionary with the credential name as key, and primary key, name, organization_id, inputs and credential_id as value.

    Returns:
        The credentials.
    """
    # oc --namespace=oldawx port-forward postgresql-5-phl5d 5432:5432
    try:
        conn = psycopg2.connect(
            dbname=AWX_SRC_DBNAME,
            user=AWX_SRC_DBUSER,
            password=AWX_SRC_DBPASSWORD,
            host=AWX_SRC_DBHOST,
            port=AWX_SRC_DBPORT,
        )
    except Exception as e:
        sys.stderr.write("I am unable to connect to the database:\n\n%s\n" % e)
        sys.exit(1)

    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute("""SELECT id, name, organization_id, inputs,
                 credential_type_id FROM main_credential""")
    table = cur.fetchall()

    # TODO what if multiple credentials with same name?
    awx_creds = {}
    for row in table:
        name = row[1]
        if name not in awx_creds:
            if isinstance(row[3], str):
                cred = dict(
                    pk=row[0],
                    name=row[1],
                    organization_id=row[2],
                    inputs=json.loads(row[3]),
                    credential_type_id=row[4],
                )
            else:
                cred = dict(
                    pk=row[0],
                    name=row[1],
                    organization_id=row[2],
                    inputs=row[3],
                    credential_type_id=row[4],
                )
            row2dict = {name: cred}
        else:
            _err = "duplicate cred found: %s", name
            sys.stderr.write(_err + "\n")
            sys.exit(1)
        awx_creds.update(row2dict)

    return awx_creds


def decrypt_inputs(awx_creds):
    """Iterate through all input fields of the credentials and decrypt where encrypted.

    Args:
        awx_creds: The credentials.

    Returns:
        The decrypted credentials.
    """
    for key, value in awx_creds.items():
        pk = value["pk"]
        inputs = value["inputs"]
        name = value["name"]
        for k, v in inputs.items():
            if v.startswith("$encrypted$"):
                encrypted = v
                encryption_key = get_encryption_key(k, pk if pk else None)
                try:
                    decrypted = decrypt_value(encryption_key, encrypted)
                except InvalidToken:
                    _err = ("Wrong encryption key for " "input field {0} for " "credential {1}").format(k, name)
                    sys.stderr.write(_err + "\n")
                    continue
                value["inputs"][k] = decrypted
        awx_creds[key] = value

    return awx_creds


def update_data_with_creds(awx_data, awx_creds):
    """Update the awx data with the credentials.

    Args:
        awx_data: The awx data.
        awx_creds: The credentials.
    """
    index = 0
    for item in awx_data:
        if item and item["asset_type"] == "credential":

            item2 = copy.deepcopy(item)
            if item["name"] in awx_creds:
                item2["inputs"] = awx_creds[item["name"]]["inputs"]
                awx_data.remove(item)
                awx_data.insert(index, item2)
            else:
                _err = ("Credential not found in the database for " "credential {0}").format(item["name"])
                sys.stderr.write(_err + "\n")
        index += 1

    return awx_data


def awx_receive_objects():
    """Get AWX exported data and decrypted credentials, update the export with clear text passwords, and dump it to stdout as json.

    Returns:
        The AWX exported data.
    """
    awx_creds = decrypt_inputs(awx_getdb_creds())
    awx_data = awx_get_data()
    update_data_with_creds(awx_data, awx_creds)

    sys.stdout.write(json.dumps(awx_data))


def awx_migratedb_conf():  # noqa: C901
    """Read the config settings table from the old awx instance, and insert or update every setting in the new awx instance.

    Returns:
        The AWX exported data.
    """
    # oc --namespace=oldawx port-forward postgresql-5-phl5d 5432:5432
    try:
        conn1 = psycopg2.connect(
            dbname=AWX_SRC_DBNAME,
            user=AWX_SRC_DBUSER,
            password=AWX_SRC_DBPASSWORD,
            host=AWX_SRC_DBHOST,
            port=AWX_SRC_DBPORT,
        )
    except Exception as e:
        sys.stderr.write("I am unable to connect to source database:\n\n%s\n" % e)
        sys.exit(1)

    cur1 = conn1.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur1.execute("SELECT id, key, value, user_id FROM conf_setting")
    table = cur1.fetchall()
    cur1.close()

    # oc --namespace=newawx port-forward postgresql-5-phl5d 5433:5432
    try:
        conn2 = psycopg2.connect(
            dbname=AWX_DST_DBNAME,
            user=AWX_DST_DBUSER,
            password=AWX_DST_DBPASSWORD,
            host=AWX_DST_DBHOST,
            port=AWX_DST_DBPORT,
        )
    except Exception as e:
        sys.stderr.write("I am unable to connect to destination database:\n\n%s\n" % e)
        sys.exit(1)

    def _insert_update(conn2, row):
        """Insert or update a row in the new awx instance.

        Args:
            conn2: The connection to the new awx instance.
            row: The row to insert or update.
        """
        key = row[0]
        cur2 = conn2.cursor()
        cur2.execute("SELECT value FROM conf_setting WHERE key = '%s'" % key)
        _result = cur2.fetchall()
        cur2.close()
        if len(_result) == 0:
            sql = "INSERT INTO conf_setting (created, modified, key, value, user_id) VALUES (%s, %s, %s, %s, %s)"
            row.insert(0, str(datetime.datetime.now()))
            row.insert(0, str(datetime.datetime.now()))
        else:
            sql = "UPDATE conf_setting SET (key, value, user_id) = (%s, %s, %s) WHERE key = '{0}'".format(key)

        # sys.stderr.write("%s <- %s\n\n" %(sql, row))
        cur2 = conn2.cursor()
        cur2.execute(sql, row)
        conn2.commit()
        cur2.close()

    for row in table:
        v = row[2]
        if v and v.strip(r"\'\"").startswith("$encrypted$"):
            v = v.strip(r"\'\"")
            pk = row[0]
            k = row[1]
            encryption_key = get_encryption_key(k, pk if pk else None)
            try:
                v = decrypt_value(encryption_key, v)
            except InvalidToken:
                _err = "Wrong encryption key for " "config field {0}, you will need to update this manually.".format(k)
                sys.stderr.write(_err + "\n")
                continue
            print(v)
        row[2] = v
        row.pop(0)
        _insert_update(conn2, row)

    # TODO update LDAP password
    # tower-cli setting set AUTH_LDAP_BIND_PASSWORD


def main():
    """Migrate config settings from old to new awx instance.

    Returns:
        The AWX exported data.
    """
    awx_migratedb_conf()
    awx_receive_objects()


if __name__ == "__main__":
    main()
