# To use this code, make sure you
#
#     import json
#
# and then, to convert JSON from a string, do
#
#     result = mdhead_from_dict(json.loads(json_string))

from typing import Any, Callable, List, Type, TypeVar, cast

T = TypeVar("T")


def from_str(x: Any) -> str:
    assert isinstance(x, str)
    return x


def to_class(c: Type[T], x: Any) -> dict:
    assert isinstance(x, c)
    return cast(Any, x).to_dict()


def from_list(f: Callable[[Any], T], x: Any) -> List[T]:
    assert isinstance(x, list)
    return [f(y) for y in x]


class Labels:
    enim: str
    ad8: str

    def __init__(self, enim: str, ad8: str) -> None:
        self.enim = enim
        self.ad8 = ad8

    @staticmethod
    def from_dict(obj: Any) -> 'Labels':
        assert isinstance(obj, dict)
        enim = from_str(obj.get("enim__"))
        ad8 = from_str(obj.get("ad8"))
        return Labels(enim, ad8)

    def to_dict(self) -> dict:
        result: dict = {}
        result["enim__"] = from_str(self.enim)
        result["ad8"] = from_str(self.ad8)
        return result


class Access:
    value: str

    def __init__(self, value: str) -> None:
        self.value = value

    @staticmethod
    def from_dict(obj: Any) -> 'Access':
        assert isinstance(obj, dict)
        value = from_str(obj.get("value"))
        return Access(value)

    def to_dict(self) -> dict:
        result: dict = {}
        result["value"] = from_str(self.value)
        return result


class Collaborator:
    id: str
    access: Access

    def __init__(self, id: str, access: Access) -> None:
        self.id = id
        self.access = access

    @staticmethod
    def from_dict(obj: Any) -> 'Collaborator':
        assert isinstance(obj, dict)
        id = from_str(obj.get("id"))
        access = Access.from_dict(obj.get("access"))
        return Collaborator(id, access)

    def to_dict(self) -> dict:
        result: dict = {}
        result["id"] = from_str(self.id)
        result["access"] = to_class(Access, self.access)
        return result


class Public:
    type: str

    def __init__(self, type: str) -> None:
        self.type = type

    @staticmethod
    def from_dict(obj: Any) -> 'Public':
        assert isinstance(obj, dict)
        type = from_str(obj.get("type"))
        return Public(type)

    def to_dict(self) -> dict:
        result: dict = {}
        result["type"] = from_str(self.type)
        return result


class Ownership:
    owner: str
    groups: List[Collaborator]
    collaborators: List[Collaborator]
    public: Public

    def __init__(self, owner: str, groups: List[Collaborator], collaborators: List[Collaborator], public: Public) -> None:
        self.owner = owner
        self.groups = groups
        self.collaborators = collaborators
        self.public = public

    @staticmethod
    def from_dict(obj: Any) -> 'Ownership':
        assert isinstance(obj, dict)
        owner = from_str(obj.get("owner"))
        groups = from_list(Collaborator.from_dict, obj.get("groups"))
        collaborators = from_list(Collaborator.from_dict, obj.get("collaborators"))
        public = Public.from_dict(obj.get("public"))
        return Ownership(owner, groups, collaborators, public)

    def to_dict(self) -> dict:
        result: dict = {}
        result["owner"] = from_str(self.owner)
        result["groups"] = from_list(lambda x: to_class(Collaborator, x), self.groups)
        result["collaborators"] = from_list(lambda x: to_class(Collaborator, x), self.collaborators)
        result["public"] = to_class(Public, self.public)
        return result


class Metadata:
    name: str
    org_id: str
    owner: str
    labels: Labels
    ownership: Ownership
    uid: str

    def __init__(self, name: str, org_id: str, owner: str, labels: Labels, ownership: Ownership, uid: str) -> None:
        self.name = name
        self.org_id = org_id
        self.owner = owner
        self.labels = labels
        self.ownership = ownership
        self.uid = uid

    @staticmethod
    def from_dict(obj: Any) -> 'Metadata':
        assert isinstance(obj, dict)
        name = from_str(obj.get("name"))
        org_id = from_str(obj.get("org_id"))
        owner = from_str(obj.get("owner"))
        labels = Labels.from_dict(obj.get("labels"))
        ownership = Ownership.from_dict(obj.get("ownership"))
        uid = from_str(obj.get("uid"))
        return Metadata(name, org_id, owner, labels, ownership, uid)

    def to_dict(self) -> dict:
        result: dict = {}
        result["name"] = from_str(self.name)
        result["org_id"] = from_str(self.org_id)
        result["owner"] = from_str(self.owner)
        result["labels"] = to_class(Labels, self.labels)
        result["ownership"] = to_class(Ownership, self.ownership)
        result["uid"] = from_str(self.uid)
        return result


class MetadataHeader:
    metadata: Metadata

    def __init__(self, metadata: Metadata) -> None:
        self.metadata = metadata

    @staticmethod
    def from_dict(obj: Any) -> 'MetadataHeader':
        assert isinstance(obj, dict)
        metadata = Metadata.from_dict(obj.get("metadata"))
        return MetadataHeader(metadata)

    def to_dict(self) -> dict:
        result: dict = {}
        result["metadata"] = to_class(Metadata, self.metadata)
        return result


def mdhead_from_dict(s: Any) -> MetadataHeader:
    return MetadataHeader.from_dict(s)


def mdhead_to_dict(x: MetadataHeader) -> Any:
    return to_class(MetadataHeader, x)
