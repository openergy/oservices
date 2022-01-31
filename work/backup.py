import os
import shutil
import re
import logging
import sys
import subprocess

import ftputil

from .. import mkdir

logger = logging.getLogger(__name__)

OUT_PATH, ERR_PATH = "admin.out", "admin.err"


def run_command(command, shell=False):
    with open(OUT_PATH, "ab") as out_f, open(ERR_PATH, "ab") as err_f:
        out_f.write(subprocess.check_output(command, shell=shell, stderr=err_f))


def get_dir_info(names, prefix):
    # prepare file patterns
    patterns = dict(
        tarball=r"^%s-(.+).(\d{8}).master.tar.gz$" % prefix,
        pgsql=r"^%s-pgsql-(.+).(\d{8}).sql.bz2$" % prefix
    )
    md5_pattern = r"^%s-\d{8}.md5" % prefix

    # prepare files dict
    dir_info = {}  # {date_str: {category: {ref: path, ...

    # iter in paths
    for name in names:
        assert os.path.basename(name) == name
        if name == ".ftpquota":
            continue
        if re.search(md5_pattern, name) is not None:
            continue
        for category, pat in patterns.items():
            match = re.search(pat, name)
            if match is not None:
                break
        else:
            logger.warning(
                "unknown file pattern in given refs, skipping",
                extra=dict(name=name)
            )
            continue

        # complete dictionary
        ref, date_str = match.group(1), match.group(2)

        if date_str not in dir_info:
            dir_info[date_str] = {}

        dates = dir_info[date_str]
        if category not in dates:
            dates[category] = {}

        assert ref not in dates[category], "same refs for same (date_str, category), should not happen"

        dates[category][ref] = name

    return dir_info


def get_file_name(dir_info, category, ref):
    assert category in dir_info, \
        "no files matching %s pattern, although %s pattern is asked: %s" % (
            category, category, dir_info)
    category_info = dir_info[category]
    assert ref in category_info, \
        "required ref for %s not found: %s \n(%s)" % (category, ref, category_info)
    return category_info[ref]


def restore(component, parsed_args, settings):
    assert sum([parsed_args.download_only, parsed_args.unzip_only, parsed_args.load_only]) <= 1, \
        "can't use download_only or unzip_only or load_only at the same time"

    # check settings
    assert settings.BACKUP is not None, "must provide backup info in settings"

    root_temp_dir = settings.BACKUP.get("root_temp_dir")
    assert root_temp_dir is not None, "must provide root_temp_dir to backup"

    assert os.path.isdir(root_temp_dir), \
        "root_temp_dir is not a directory: %s" % root_temp_dir

    host = settings.BACKUP.get("host")
    login = settings.BACKUP.get("login")
    password = settings.BACKUP.get("password")

    assert None not in (host, login, password), \
        "all backup ftp info was not provided (backup_host, backup_login, backup_password)"

    prefix = settings.BACKUP.get("prefix")
    assert prefix is not None, "must provide backup_prefix"

    tarball = None
    if "tarball" in settings.BACKUP:
        tarball = settings.BACKUP["tarball"]
        assert "refs" in tarball and isinstance(tarball["refs"], dict) and len(tarball["refs"]) > 0, \
            "tarball must contain a refs field being a dict of at least 1 element"

    pgsql = None
    if "pgsql" in settings.BACKUP:
        pgsql = settings.BACKUP["pgsql"]
        assert "refs" in pgsql and len(pgsql["refs"]) > 0, \
            "pgsql must contain a refs fields being a list of at least 1 element"
        assert None not in (pgsql.get("user"), pgsql.get("password")), \
            "must provide db user and password to restore backup"

        # manage optional arguments
        if "host" not in pgsql:
            pgsql["host"] = "localhost"

        if "port" not in pgsql:
            pgsql["port"] = "5432"

        if "admin" not in pgsql:
            pgsql["admin"] = pgsql["user"]

        if "admin_password" not in pgsql:
            pgsql["admin_password"] = pgsql["password"]

    downloaded_backup_dir_path = os.path.join(
        root_temp_dir,
        "%s-%s" % (component.service_name, component.name)
    )

    # download
    if not (parsed_args.load_only or parsed_args.unzip_only):
        if os.path.exists(downloaded_backup_dir_path):
            shutil.rmtree(downloaded_backup_dir_path)
        mkdir(downloaded_backup_dir_path)

        # download files
        with ftputil.FTPHost(host, login, password) as ftp_host:
            # get refs
            names = ftp_host.listdir(ftp_host.curdir)

            # retrieve info
            dir_info = get_dir_info(names, prefix)

            # get last date
            assert len(dir_info) > 0, "not enough files to extract information"
            _, dir_info = sorted(dir_info.items())[-1]

            # download
            for category in ("tarball", "pgsql"):
                category_settings = locals()[category]
                if category_settings is not None:
                    for ref in category_settings["refs"]:
                        name = get_file_name(dir_info, category, ref)
                        sys.stdout.write("   [..] downloading: %s" % name)
                        sys.stdout.flush()
                        ftp_host.download(name, os.path.join(downloaded_backup_dir_path, name))
                        sys.stdout.write("\r   [ok] downloading: %s\n" % name)

    # unzip
    if not (parsed_args.load_only or parsed_args.download_only):
        # get refs and info
        names = os.listdir(downloaded_backup_dir_path)

        # info
        dir_info = get_dir_info(names, prefix)

        # get last date
        assert len(dir_info) > 0, "not enough files to extract information"
        _, dir_info = sorted(dir_info.items())[-1]

        # unzip
        if tarball is not None:
            for ref, base_dir in tarball["refs"].items():
                name = get_file_name(dir_info, "tarball", ref)
                archive_path = os.path.join(downloaded_backup_dir_path, name)
                cmd = "tar -zxvf %s -C %s" % (archive_path, downloaded_backup_dir_path)

                # call
                sys.stdout.write("   [..] extracting: %s" % archive_path)
                sys.stdout.flush()
                run_command(cmd.split(" "))

                # move
                useful_path = os.path.join(downloaded_backup_dir_path, base_dir.strip("/"), ref)
                os.rename(useful_path, os.path.join(downloaded_backup_dir_path, ref))

                # cleanup (will only work on linux I think...)
                obsolete_path = os.path.join(downloaded_backup_dir_path, base_dir.strip("/").split(os.path.sep)[0])
                shutil.rmtree(obsolete_path)
                os.remove(archive_path)

                sys.stdout.write("\r   [ok] extracting: %s\n" % archive_path)

        if pgsql is not None:
            for ref in pgsql["refs"]:
                name = get_file_name(dir_info, "pgsql", ref)
                archive_path = os.path.join(downloaded_backup_dir_path, name)

                # call
                sys.stdout.write("   [..] extracting: %s" % ref)
                sys.stdout.flush()
                cmd = "bzip2 -d %s" % archive_path
                run_command(cmd.split(" "))

                # rename and delete
                os.rename(
                    archive_path[:-4],
                    os.path.join(downloaded_backup_dir_path, "%s.sql" % ref))  # we removed .bz2

                sys.stdout.write("\r   [ok] extracting: %s\n" % ref)

    # load
    if not (parsed_args.download_only or parsed_args.unzip_only):
        # tarballs
        if tarball is not None:
            for ref in tarball["refs"]:
                src_path = os.path.join(downloaded_backup_dir_path, ref)
                assert os.path.isdir(src_path), "tarball source must be a directory, not found: %s" % src_path

                dst_path = os.path.join(settings.APP_DATA_DIR_PATH, "data", ref)
                if os.path.exists(dst_path):
                    shutil.rmtree(dst_path)

                sys.stdout.write("   [..] moving: %s" % ref)
                sys.stdout.flush()
                shutil.move(src_path, dst_path)
                sys.stdout.write("\r   [ok] moving: %s\n" % ref)

        # pgsqls
        if pgsql is not None:
            for ref in pgsql["refs"]:
                sys.stdout.write("   [..] dumping in postgresql: %s" % ref)
                sys.stdout.flush()

                # delete existing db
                cmd = "PGPASSWORD={password} dropdb -h {host} -p {port} -U {user} '{db}' --if-exists".format(
                    password=pgsql["password"],
                    host=pgsql["host"],
                    port=pgsql["port"],
                    user=pgsql["user"],
                    db=ref
                )
                run_command(cmd, shell=True)  # we use shell=True for pgpassword

                # create new db
                run_command(
                    "PGPASSWORD={admin_password} createdb -h {host} -p {port} -U {admin} -O {owner} '{db}'".format(
                        admin=pgsql["admin"],
                        admin_password=pgsql["admin_password"],
                        host=pgsql["host"],
                        port=pgsql["port"],
                        owner=pgsql["user"],
                        db=ref
                    ),
                    shell=True)

                # dump db
                file_path = os.path.join(downloaded_backup_dir_path, "%s.sql" % ref)
                cmd = "PGPASSWORD={password} psql -h {host} -p {port} -U {user} {db} < {file_path}".format(
                    password=pgsql["password"],
                    host=pgsql["host"],
                    port=pgsql["port"],
                    user=pgsql["user"],
                    db=ref,
                    file_path=file_path
                )
                run_command(cmd, shell=True)

                os.remove(file_path)  # for coherence with tarballs

                # tell finished
                sys.stdout.write("\r   [ok] dumping in postgresql: %s\n" % ref)

