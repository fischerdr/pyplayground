# To use this code, make sure you
#
#     import json
#
# and then, to convert JSON from a string, do
#
#     result = welcome3_from_dict(json.loads(json_string))
from typing import Any, Callable, List, Optional, Type, TypeVar, cast

from pxclients.metadataheader import Metadata

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


def from_none(x: Any) -> Any:
    assert x is None
    return x


def from_union(fs, x):
    for f in fs:
        try:
            return f(x)
        except:
            pass
    assert False


def from_bool(x: Any) -> bool:
    assert isinstance(x, bool)
    return x

class IncrementalCount:
    count: str

    def __init__(self, count: str) -> None:
        self.count = count

    @staticmethod
    def from_dict(obj: Any) -> 'IncrementalCount':
        assert isinstance(obj, dict)
        count = from_str(obj.get("count"))
        return IncrementalCount(count)

    def to_dict(self) -> dict:
        result: dict = {}
        result["count"] = from_str(self.count)
        return result

class Interval:
    minutes: str
    retain: str
    incremental_count: IncrementalCount

    def __init__(self, minutes: str, retain: str, incremental_count: IncrementalCount) -> None:
        self.minutes = minutes
        self.retain = retain
        self.incremental_count = incremental_count

    @staticmethod
    def from_dict(obj: Any) -> 'Interval':
        assert isinstance(obj, dict)
        minutes = from_str(obj.get("minutes"))
        retain = from_str(obj.get("retain"))
        incremental_count = IncrementalCount.from_dict(obj.get("incremental_count"))
        return Interval(minutes, retain, incremental_count)

    def to_dict(self) -> dict:
        result: dict = {}
        result["minutes"] = from_str(self.minutes)
        result["retain"] = from_str(self.retain)
        result["incremental_count"] = to_class(IncrementalCount, self.incremental_count)
        return result

class Daily:
    time: str
    retain: str
    incremental_count: IncrementalCount
    date: Optional[str]
    day: Optional[str]

    def __init__(self, time: str, retain: str, incremental_count: IncrementalCount, date: Optional[str], day: Optional[str]) -> None:
        self.time = time
        self.retain = retain
        self.incremental_count = incremental_count
        self.date = date
        self.day = day

    @staticmethod
    def from_dict(obj: Any) -> 'Daily':
        assert isinstance(obj, dict)
        time = from_str(obj.get("time"))
        retain = from_str(obj.get("retain"))
        incremental_count = IncrementalCount.from_dict(obj.get("incremental_count"))
        date = from_union([from_str, from_none], obj.get("date"))
        day = from_union([from_str, from_none], obj.get("day"))
        return Daily(time, retain, incremental_count, date, day)

    def to_dict(self) -> dict:
        result: dict = {}
        result["time"] = from_str(self.time)
        result["retain"] = from_str(self.retain)
        result["incremental_count"] = to_class(IncrementalCount, self.incremental_count)
        result["date"] = from_union([from_str, from_none], self.date)
        result["day"] = from_union([from_str, from_none], self.day)
        return result

class Weekly:
    day: str
    time: str
    retain: str
    incremental_count: IncrementalCount

    def __init__(self, day: str, time: str, retain: str, incremental_count: IncrementalCount) -> None:
        self.day = day
        self.time = time
        self.retain = retain
        self.incremental_count = incremental_count

    @staticmethod
    def from_dict(obj: Any) -> 'Weekly':
        assert isinstance(obj, dict)
        day = from_str(obj.get("day"))
        time = from_str(obj.get("time"))
        retain = from_str(obj.get("retain"))
        incremental_count = IncrementalCount.from_dict(obj.get("incremental_count"))
        return Weekly(day, time, retain, incremental_count)

    def to_dict(self) -> dict:
        result: dict = {}
        result["day"] = from_str(self.day)
        result["time"] = from_str(self.time)
        result["retain"] = from_str(self.retain)
        result["incremental_count"] = to_class(IncrementalCount, self.incremental_count)
        return result


class Monthly:
    date: Optional[str]
    time: str
    retain: str
    incremental_count: IncrementalCount
    day: Optional[str]

    def __init__(self, date: Optional[str], time: str, retain: str, incremental_count: IncrementalCount, day: Optional[str]) -> None:
        self.date = date
        self.time = time
        self.retain = retain
        self.incremental_count = incremental_count
        self.day = day

    @staticmethod
    def from_dict(obj: Any) -> 'Monthly':
        assert isinstance(obj, dict)
        date = from_union([from_str, from_none], obj.get("date"))
        time = from_str(obj.get("time"))
        retain = from_str(obj.get("retain"))
        incremental_count = IncrementalCount.from_dict(obj.get("incremental_count"))
        day = from_union([from_str, from_none], obj.get("day"))
        return Monthly(date, time, retain, incremental_count, day)

    def to_dict(self) -> dict:
        result: dict = {}
        result["date"] = from_union([from_str, from_none], self.date)
        result["time"] = from_str(self.time)
        result["retain"] = from_str(self.retain)
        result["incremental_count"] = to_class(IncrementalCount, self.incremental_count)
        result["day"] = from_union([from_str, from_none], self.day)
        return result


class SchedulePolicy:
    interval: Interval
    daily: Daily
    weekly: Weekly
    monthly: Monthly
    backup_schedule: List[str]
    for_object_lock: bool
    auto_delete: bool

    def __init__(self, interval: Interval, daily: Daily, weekly: Weekly, monthly: Monthly, backup_schedule: List[str], for_object_lock: bool, auto_delete: bool) -> None:
        self.interval = interval
        self.daily = daily
        self.weekly = weekly
        self.monthly = monthly
        self.backup_schedule = backup_schedule
        self.for_object_lock = for_object_lock
        self.auto_delete = auto_delete

    @staticmethod
    def from_dict(obj: Any) -> 'SchedulePolicy':
        assert isinstance(obj, dict)
        interval = Interval.from_dict(obj.get("interval"))
        daily = Daily.from_dict(obj.get("daily"))
        weekly = Daily.from_dict(obj.get("weekly"))
        monthly = Daily.from_dict(obj.get("monthly"))
        backup_schedule = from_list(from_str, obj.get("backup_schedule"))
        for_object_lock = from_bool(obj.get("for_object_lock"))
        auto_delete = from_bool(obj.get("auto_delete"))
        return SchedulePolicy(interval, daily, weekly, monthly, backup_schedule, for_object_lock, auto_delete)

    def to_dict(self) -> dict:
        result: dict = {}
        result["interval"] = to_class(Interval, self.interval)
        result["daily"] = to_class(Daily, self.daily)
        result["weekly"] = to_class(Daily, self.weekly)
        result["monthly"] = to_class(Daily, self.monthly)
        result["backup_schedule"] = from_list(from_str, self.backup_schedule)
        result["for_object_lock"] = from_bool(self.for_object_lock)
        result["auto_delete"] = from_bool(self.auto_delete)
        return result


class SchedPolicy:
    metadata: Metadata
    schedule_policy: SchedulePolicy

    def __init__(self, metadata: Metadata, schedule_policy: SchedulePolicy) -> None:
        self.metadata = metadata
        self.schedule_policy = schedule_policy

    @staticmethod
    def from_dict(obj: Any) -> 'SchedPolicy':
        assert isinstance(obj, dict)
        metadata = Metadata.from_dict(obj.get("metadata"))
        schedule_policy = SchedulePolicy.from_dict(obj.get("schedule_policy"))
        return SchedPolicy(metadata, schedule_policy)

    def to_dict(self) -> dict:
        result: dict = {}
        result["metadata"] = to_class(Metadata, self.metadata)
        result["schedule_policy"] = to_class(SchedulePolicy, self.schedule_policy)
        return result


def welcome3_from_dict(s: Any) -> SchedPolicy:
    return SchedPolicy.from_dict(s)


def welcome3_to_dict(x: SchedPolicy) -> Any:
    return to_class(SchedPolicy, x)
