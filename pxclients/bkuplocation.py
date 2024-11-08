# To use this code, make sure you
#
#     import json
#
# and then, to convert JSON from a string, do
#
#     result = bkuploc_from_dict(json.loads(json_string))
from pxclients.metadataheader import Metadata

from typing import Any, List, TypeVar, Type, cast, Callable


T = TypeVar("T")


def from_str(x: Any) -> str:
    assert isinstance(x, str)
    return x


def from_bool(x: Any) -> bool:
    assert isinstance(x, bool)
    return x


def to_class(c: Type[T], x: Any) -> dict:
    assert isinstance(x, c)
    return cast(Any, x).to_dict()


def from_list(f: Callable[[Any], T], x: Any) -> List[T]:
    assert isinstance(x, list)
    return [f(y) for y in x]


class CloudCredentialRef:
    name: str
    uid: str

    def __init__(self, name: str, uid: str) -> None:
        self.name = name
        self.uid = uid

    @staticmethod
    def from_dict(obj: Any) -> 'CloudCredentialRef':
        assert isinstance(obj, dict)
        name = from_str(obj.get("name"))
        uid = from_str(obj.get("uid"))
        return CloudCredentialRef(name, uid)

    def to_dict(self) -> dict:
        result: dict = {}
        result["name"] = from_str(self.name)
        result["uid"] = from_str(self.uid)
        return result


class NFSConfig:
    server_addr: str
    sub_path: str
    mount_option: str

    def __init__(self, server_addr: str, sub_path: str, mount_option: str) -> None:
        self.server_addr = server_addr
        self.sub_path = sub_path
        self.mount_option = mount_option

    @staticmethod
    def from_dict(obj: Any) -> 'NFSConfig':
        assert isinstance(obj, dict)
        server_addr = from_str(obj.get("server_addr"))
        sub_path = from_str(obj.get("sub_path"))
        mount_option = from_str(obj.get("mount_option"))
        return NFSConfig(server_addr, sub_path, mount_option)

    def to_dict(self) -> dict:
        result: dict = {}
        result["server_addr"] = from_str(self.server_addr)
        result["sub_path"] = from_str(self.sub_path)
        result["mount_option"] = from_str(self.mount_option)
        return result


class AzureEnvironment:
    type: str

    def __init__(self, type: str) -> None:
        self.type = type

    @staticmethod
    def from_dict(obj: Any) -> 'AzureEnvironment':
        assert isinstance(obj, dict)
        type = from_str(obj.get("type"))
        return AzureEnvironment(type)

    def to_dict(self) -> dict:
        result: dict = {}
        result["type"] = from_str(self.type)
        return result


class S3Config:
    endpoint: str
    region: str
    disable_ssl: bool
    disable_path_style: bool
    storage_class: str
    sse_type: str
    azure_environment: AzureEnvironment
    azure_resource_group_name: str

    def __init__(self, endpoint: str, region: str, disable_ssl: bool, disable_path_style: bool, storage_class: str, sse_type: str, azure_environment: AzureEnvironment, azure_resource_group_name: str) -> None:
        self.endpoint = endpoint
        self.region = region
        self.disable_ssl = disable_ssl
        self.disable_path_style = disable_path_style
        self.storage_class = storage_class
        self.sse_type = sse_type
        self.azure_environment = azure_environment
        self.azure_resource_group_name = azure_resource_group_name

    @staticmethod
    def from_dict(obj: Any) -> 'S3Config':
        assert isinstance(obj, dict)
        endpoint = from_str(obj.get("endpoint"))
        region = from_str(obj.get("region"))
        disable_ssl = from_bool(obj.get("disable_ssl"))
        disable_path_style = from_bool(obj.get("disable_path_style"))
        storage_class = from_str(obj.get("storage_class"))
        sse_type = from_str(obj.get("sse_type"))
        azure_environment = AzureEnvironment.from_dict(obj.get("azure_environment"))
        azure_resource_group_name = from_str(obj.get("azure_resource_group_name"))
        return S3Config(endpoint, region, disable_ssl, disable_path_style, storage_class, sse_type, azure_environment, azure_resource_group_name)

    def to_dict(self) -> dict:
        result: dict = {}
        result["endpoint"] = from_str(self.endpoint)
        result["region"] = from_str(self.region)
        result["disable_ssl"] = from_bool(self.disable_ssl)
        result["disable_path_style"] = from_bool(self.disable_path_style)
        result["storage_class"] = from_str(self.storage_class)
        result["sse_type"] = from_str(self.sse_type)
        result["azure_environment"] = to_class(AzureEnvironment, self.azure_environment)
        result["azure_resource_group_name"] = from_str(self.azure_resource_group_name)
        return result


class Status:
    status: str
    reason: str

    def __init__(self, status: str, reason: str) -> None:
        self.status = status
        self.reason = reason

    @staticmethod
    def from_dict(obj: Any) -> 'Status':
        assert isinstance(obj, dict)
        status = from_str(obj.get("status"))
        reason = from_str(obj.get("reason"))
        return Status(status, reason)

    def to_dict(self) -> dict:
        result: dict = {}
        result["status"] = from_str(self.status)
        result["reason"] = from_str(self.reason)
        return result


class BackupLocation:
    type: str
    path: str
    encryption_key: str
    cloud_credential: str
    status: Status
    delete_backups: bool
    validate_cloud_credential: bool
    cloud_credential_ref: CloudCredentialRef
    object_lock_enabled: bool
    s3_config: S3Config
    nfs_config: NFSConfig

    def __init__(self, type: str, path: str, encryption_key: str, cloud_credential: str, status: Status, delete_backups: bool, validate_cloud_credential: bool, cloud_credential_ref: CloudCredentialRef, object_lock_enabled: bool, s3_config: S3Config, nfs_config: NFSConfig) -> None:
        self.type = type
        self.path = path
        self.encryption_key = encryption_key
        self.cloud_credential = cloud_credential
        self.status = status
        self.delete_backups = delete_backups
        self.validate_cloud_credential = validate_cloud_credential
        self.cloud_credential_ref = cloud_credential_ref
        self.object_lock_enabled = object_lock_enabled
        self.s3_config = s3_config
        self.nfs_config = nfs_config

    @staticmethod
    def from_dict(obj: Any) -> 'BackupLocation':
        assert isinstance(obj, dict)
        type = from_str(obj.get("type"))
        path = from_str(obj.get("path"))
        encryption_key = from_str(obj.get("encryption_key"))
        cloud_credential = from_str(obj.get("cloud_credential"))
        status = Status.from_dict(obj.get("status"))
        delete_backups = from_bool(obj.get("delete_backups"))
        validate_cloud_credential = from_bool(obj.get("validate_cloud_credential"))
        cloud_credential_ref = CloudCredentialRef.from_dict(obj.get("cloud_credential_ref"))
        object_lock_enabled = from_bool(obj.get("object_lock_enabled"))
        s3_config = S3Config.from_dict(obj.get("s3_config"))
        nfs_config = NFSConfig.from_dict(obj.get("nfs_config"))
        return BackupLocation(type, path, encryption_key, cloud_credential, status, delete_backups, validate_cloud_credential, cloud_credential_ref, object_lock_enabled, s3_config, nfs_config)

    def to_dict(self) -> dict:
        result: dict = {}
        result["type"] = from_str(self.type)
        result["path"] = from_str(self.path)
        result["encryption_key"] = from_str(self.encryption_key)
        result["cloud_credential"] = from_str(self.cloud_credential)
        result["status"] = to_class(Status, self.status)
        result["delete_backups"] = from_bool(self.delete_backups)
        result["validate_cloud_credential"] = from_bool(self.validate_cloud_credential)
        result["cloud_credential_ref"] = to_class(CloudCredentialRef, self.cloud_credential_ref)
        result["object_lock_enabled"] = from_bool(self.object_lock_enabled)
        result["s3_config"] = to_class(S3Config, self.s3_config)
        result["nfs_config"] = to_class(NFSConfig, self.nfs_config)
        return result


class BackupLocation:
    metadata: Metadata
    backup_location: BackupLocation

    def __init__(self, metadata: Metadata, backup_location: BackupLocation) -> None:
        self.metadata = metadata
        self.backup_location = backup_location

    @staticmethod
    def from_dict(obj: Any) -> 'BackupLocation':
        assert isinstance(obj, dict)
        metadata = Metadata.from_dict(obj.get("metadata"))
        backup_location = BackupLocation.from_dict(obj.get("backup_location"))
        return BackupLocation(metadata, backup_location)

    def to_dict(self) -> dict:
        result: dict = {}
        result["metadata"] = to_class(Metadata, self.metadata)
        result["backup_location"] = to_class(BackupLocation, self.backup_location)
        return result


def bkuploc_from_dict(s: Any) -> BackupLocation:
    return BackupLocation.from_dict(s)


def bkuploc_to_dict(x: BackupLocation) -> Any:
    return to_class(BackupLocation, x)
