"""Test the Dometic Büttner BMS implementation."""

import asyncio
from collections.abc import Awaitable, Buffer, Callable
import contextlib
from enum import Enum, auto
import inspect
from logging import DEBUG
from typing import Any, Final, Literal, Self
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.service import BleakGATTService
import pytest

from aiobmsble import BMSConfig, BMSSample, TempSensor as TS
from aiobmsble.bms.dometic_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import LOGGER, MockBleakClient
from tests.test_basebms import BMSBasicTests

BT_FRAME_SIZE = 32

_PROTO_DEFS: Final[tuple[bytes, ...]] = (
    b"#\x85\x00\xf2\x00\x00\x00\x00",
    b"#\x85\x00\x02\x051\x81\x11",
    b"#\x85\x005\nW\x07X",
    b"#\x85\x00V\x0c\xf3\x0c\xf4",
    b"#\x85\x00W\x0c\xf2\x0c\xf0",
    b"#\x85\x00\x0b\\\xff\xff\xff",
    b"#\x85\x006\x07%\xff\xff",
    b"#\x85\x00\x0c\x02\x80\xff\xff",
    b"#\x85\x00\xf1\x00\x00\x00\x00",
    b"#\x85\x00\x90\x02\x0f\x02\x0f",
    b"#\x85\x004\xff\xff\x08\x81",
    b"#\x85\x00\x07\x00\x00\x00\x96",
    b"#\x85\x00\x0ed\x00\x00\x00",
    b"#\x85\x00T\x00KAA",
    b"#\x85\x00\xc0\x00\x00\x00\x00",
    b"#\x85\x00`@\x00\x04\x00",
    b"#\x85\x00U\x00&&\xa3",
    b"#\x85\x00\xa1\x04\x03\x02\x08",
    b"#M\x08\xb1\x84\xb3T\x88",
    b"#M\x01\xb1t\xb2\xfeA",
    b"#M\x06\xb1\x9c\xb2\x9eV",
    b"#M\x0e\xb1\x963\x19N",
    b"#M\x0b\xb1\x8c\xb3N\x9b",
    b"#M\x0c\xb1\x94\xb2\xbb\\",
    b"#M\x04\xb1\x8c\xb2\xee\x14",
    b"#M\x03\xb1v2\xa5\x13",
    b"#M\x02\xb1\x963 \x02",
    b"#M\x07\xb1\x94\xb36\xf7",
    b"#M\x0f\xb1L\xb2\xab/",
    b"#M\x00\xb1v2\xa4@",
    b"#M\x05\xb1\x963\x1a\xf5",
    b"#M\r\xb1V3\x01\x1d",
    b"#M\t\xb1\x863J\xb9",
    b"#\x85\x0f\x02\x050\x81!",
    b"#\x85\x0f\x0b\\\xff\xff\xff",
    b"#\x85\x0f\x0c\x02\x80\xff\xff",
    b"#\x85\x0f\x07\x00\x00\x00\x96",
    b"#\x85\x0f4\xff\xff\t;",
    b"#\x85\x0f\x0ed\x00\x00\x00",
    b"#\x85\x0f``\x00\x01\x00",
    b"#\x85\x0f5\n\xac\x07l",
    b"#\x85\x0f6\x07\x15\xff\xff",
    b"#\x85\x0f\xf1\x00\x00\x00\x00",
    b"#\x85\x0f\xf2\x00\x00\x00\x00",
    b"#\x85\x0f\xc0\x00\x00\x00\x00",
    b"#\x85\x0f\xc0\x00\x00\x00",  # invalid length
    b"#\x85\x0fT\x0fKAA",
    b"#\x85\x0fU\x0f&&{",
    b"#\x85\x0fV\x0c\xee\x0c\xef",
    b"#\x85\x0fW\x0c\xef\x0c\xeb",
    b"#\x85\x0f\xa1\x04\x03\x02\x08",
    b"#\x85\x0f\x90\x01\x0f\x01\x0f",
    b"#\x85\x0f\xb0\x10%\x00\x00",
    b'#\x85\x0f\xb1\x963"@',
    b"#\x85\x0f\x00\x00\x00\x00\x00",
    b"#\x85\x0f\xb3\x06@\x06@",
    b"#\x85\x0f\x00\x00\x00\x00\x00",
    b"#\x85\x0f\x00\x00\x00\x00\x00",
    b"#\x85\x0f\x00\x00\x00\x00\x00",
    b"#\x85\x0f\x00\x00\x00\x00\x00",
    b"#\x85\x0f\x00\x00\x00\x00\x00",
    b"#\x85\x0f\x00\x00\x00\x00\x00",
    b"#\x85\x0f\x00\x00\x00\x00\x00",
    b"#\x85\x0f\x00\x00\x00\x00\x00",
    b"#\x85\x0f\x00\x00\x00\x00\x00",
    b"#\x85\x0f\x00\x00\x00\x00\x00",
    b"#\x85\x0f\x00\x00\x00\x00\x00",
    b"MST+IMP=\xb0\x10%\x00\x00",
    b"MST+IMP=\xb1\x963 \x02",
    b"MST+IMP=\xb2\x00\x00\x00\x00",
    b"MST+IMP=\xb3\x06@\x06@",
    b"MST+IMP=\xb4\x00\x00\x00\x00",
    b"MST+IMP=\xb5\x00\x00\x00\x00",
    b"MST+IMP=\xb6\x00\x00\x00\x00",
    b"MST+IMP=\xb7\x00\x00\x00\x00",
    b"MST+IMP=\xb8\x00\x00\x00\x00",
    b"MST+IMP=\xb9\x00\x00\x00\x00",
    b"MST+IMP=\xba\x00\x00\x00\x00",
    b"MST+IMP=\xbb\x00\x00\x00\x00",
    b"MST+IMP=\xbc\x00\x00\x00\x00",
    b"MST+IMP=\xbd\x00\x00\x00\x00",
    b"MST+IMP=\xbe\x00\x00\x00\x00",
    b"MST+IMP=\xbf\x00\x00\x00\x00",
    b'#\x80\x00\xb1\x963"X',
    b"#\x85\x0f6\x07\x16\xff\xff",
    b"#\x85\x00\x0ed\x00\x00\x00",
    b"#\x85\x0f\x02\x05.\x81$",
    b"#\x85\x00V\x0c\xf3\x0c\xf4",
    b"#\x85\x0f\x0ed\x00\x00\x00",
    b"#\x85\x00\x0b\\\xff\xff\xff",
    b"#\x85\x0fU\x0f&&{",
    b"#\x85\x00\x02\x050\x81\x11",
    b"#\x85\x0f\x0c\x02\x80\xff\xff",
    b"#\x85\x00\xc0\x00\x00\x00\x00",
    b"#\x85\x0f\x07\x00\x00\x00\x96",
    b"#\x85\x00\x0c\x02\x80\xff\xff",
    b"#\x85\x0f\x0b\\\xff\xff\xff",
    b"#\x85\x00\x07\x00\x00\x00\x96",
    b"MST+NET=\x85\x8f\x01\x05\x00\x08\x04\x03\x02\x05\x01",
    b"MST+NET=\x85\x00\x01\x05\x00\x08\x04\x03\x02\x05\x04",
    b'MST+DCO=\x11"3@',
    b"#\x85\x0f\x02\x05.\x81!",
    b"#\x85\x005\nW\x07X",
    b"#\x85\x0f\x02\x05.\x81!",
    b"#\x85\x00\x0b\\\xff\xff\xff",
    b"#\x85\x0fT\x0fKAA",
    b"#\x85\x00T\x00KAA",
    b"#\x85\x0f\x02\x050\x81$",
    b"#\x85\x00\x0c\x02\x80\xff\xff",
    b"#\x85\x0f\x02\x050\x81$",
    b"#\x85\x00\x0ed\x00\x00\x00",
    b"#\x85\x0f\xf2\x00\x00\x00\x00",
    b"#\x85\x00\x02\x050\x81\x0f",
    b"#\x85\x0f\x0ed\x00\x00\x00",
    b"#\x85\x00\x07\x00\x00\x00\x96",
    b"MST+NET=\x85\x8f\x01\x05\x00\x08\x04\x03\x02\x05\x01",
    b"MST+NET=\x85\x00\x01\x05\x00\x08\x04\x03\x02\x05\x04",
    b'MST+DCO=\x11"3@',
    b"#\x85\x0f\x0c\x02\x80\xff\xff",
    b"#\x85\x006\x07%\xff\xff",
    b"#\x85\x0f\x0b\\\xff\xff\xff",
    b"#\x85\x00\x90\x02\x0f\x02\x0f",
    b"#\x85\x0f\x02\x050\x81&",
    b"#\x85\x00W\x0c\xf2\x0c\xf0",
    b"#\x85\x0f\xc0\x00\x00\x00\x00",
    b"#\x85\x00\x0b\\\xff\xff\xff",
    b"#\x85\x0f\xb0\x10%\x00\x00",
    b"#\x85\x00\x02\x050\x81\x11",
    b"#\x85\x0f\x90\x01\x0f\x01\x0f",
    b"#\x85\x00\x02\x050\x81\x11",
    b"#\x85\x0f\x02\x05/\x81!",
    b"#\x85\x00\x07\x00\x00\x00\x96",
    b"MST+NET=\x85\x8f\x01\x05\x00\x08\x04\x03\x02\x05\x01",
    b"MST+NET=\x85\x00\x01\x05\x00\x08\x04\x03\x02\x05\x04",
    b'MST+DCO=\x11"3@',
    b"#\x85\x0f\xb3\x06@\x06@",
    b"#\x85\x00\x02\x050\x81\x11",
    b"#\x85\x0f\xf1\x00\x00\x00\x00",
    b"#\x85\x00\xa1\x04\x03\x02\x08",
    b"#\x85\x0f\x02\x05/\x81!",
    b"#\x85\x00\x0b\\\xff\xff\xff",
    b"#\x85\x0f\xa1\x04\x03\x02\x08",
    b"#\x85\x00\x02\x050\x81\x11",
    b"#\x85\x0fV\x0c\xef\x0c\xef",
    b"#\x85\x004\xff\xff\x08\x80",
    b"#\x85\x0f\x07\x00\x00\x00\x96",
    b"#\x85\x00\x0b\\\xff\xff\xff",
    b"#\x85\x0f\x0b\\\xff\xff\xff",
    b"#\x85\x00\xc0\x00\x00\x00\x00",
    b"\n",
    b"MST+NET=\x85\x8f\x01\x05\x00\x08\x04\x03\x02\x05\x01",
    b"MST+NET=\x85\x00\x01\x05\x00\x08\x04\x03\x02\x05\x04",
    b'MST+DCO=\x11"3@',
    b"#\x85\x0f\x02\x05/\x81$",
    b"#\x85\x00U\x00&&\xa3",
    b"#\x85\x0f\x0c\x02\x80\xff\xff",
    b"#\x85\x00\x0b\\\xff\xff\xff",
    b"#\x85\x0fU\x0f&&{",
    b"#\x85\x00V\x0c\xf3\x0c\xf4",
    b"#\x85\x0f\x02\x05/\x81$",
    b"#\x85\x006\x07%\xff\xff",
    b"#\x85\x0f\x02\x05/\x81$",
    b"#\x85\x00\x0b\\\xff\xff\xff",
    b"#\x85\x0f\xf2\x00\x00\x00\x00",
    b"#\x85\x00\x0ed\x00\x00\x00",
    b"#\x85\x0fT\x0fKAA",
    b"#\x85\x00T\x00KAA",
    b"MST+NET=\x85\x8f\x01\x05\x00\x08\x04\x03\x02\x05\x01",
    b"MST+NET=\x85\x00\x01\x05\x00\x08\x04\x03\x02\x05\x04",
    b'MST+DCO=\x11"3@',
    b"#\x85\x0f\x0ed\x00\x00\x00",
    b"#\x85\x00\x0c\x02\x80\xff\xff",
    b'#\x85\x0f\xb1\x963"\x80',
    b"#\x85\x00\x02\x050\x81\x11",
    b"#\x85\x0f\x02\x05/\x81$",
    b"#\x85\x005\nW\x07X",
    b"MST+NET=\x85\x8f\x01\x05\x00\x08\x04\x03\x02\x05\x01",
    b"MST+NET=\x85\x00\x01\x05\x00\x08\x04\x03\x02\x05\x04",
    b'MST+DCO=\x11"3@',
    b"#\x85\x00\xf2\x00\x00\x00\x00",
    b"#\x85\x00\x02\x050\x81\x11",
    b"#\x85\x005\nW\x07X",
    b"#\x85\x00V\x0c\xf3\x0c\xf4",
    b"#\x85\x00W\x0c\xf2\x0c\xf0",
    b"#\x85\x00\x0b\\\xff\xff\xff",
    b"#\x85\x006\x07%\xff\xff",
    b"#\x85\x00\x0c\x02\x80\xff\xff",
    b"#\x85\x00\xf1\x00\x00\x00\x00",
    b"#\x85\x00\x90\x02\x0f\x02\x0f",
    b"#\x85\x004\xff\xff\x08\x80",
    b"#\x85\x00\x07\x00\x00\x00\x96",
    b"#\x85\x00\x0ed\x00\x00\x00",
    b"#\x85\x00T\x00KAA",
    b"#\x85\x00\xc0\x00\x00\x00\x00",
    b"#\x85\x00`@\x00\x04\x00",
    b"#\x85\x00U\x00&&\xa3",
    b"#\x85\x00\xa1\x04\x03\x02\x08",
    b'#M\x08\xb1\x963"X',
    b"#M\x01\xb1t\xb2\xfeA",
    b"#M\x06\xb1\x9c\xb2\x9eV",
    b"#M\x0e\xb1\x963\x19N",
    b"#M\x0b\xb1\x8c\xb3N\x9b",
    b"#M\x0c\xb1\x94\xb2\xbb\\",
    b"#M\x04\xb1\x8c\xb2\xee\x14",
    b"#M\x03\xb1v2\xa5\x13",
    b"#M\x02\xb1\x963 \x02",
    b"#M\x07\xb1\x94\xb36\xf7",
    b"#M\x0f\xb1L\xb2\xab/",
    b"#M\x00\xb1v2\xa4@",
    b"#M\x05\xb1\x963\x1a\xf5",
    b"#M\r\xb1V3\x01\x1d",
    b"#M\t\xb1\x863J\xb9",
    b"#\x85\x0f\x02\x05/\x81$",
    b"#\x85\x0f\x0b\\\xff\xff\xff",
    b"#\x85\x0f\x0c\x02\x80\xff\xff",
    b"#\x85\x0f\x07\x00\x00\x00\x96",
    b"#\x85\x0f4\xff\xff\t:",
    b"#\x85\x0f\x0ed\x00\x00\x00",
    b"#\x85\x0f``\x00\x01\x00",
    b"#\x85\x0f5\n\xac\x07l",
    b"#\x85\x0f6\x07\x16\xff\xff",
    b"#\x85\x0f\xf1\x00\x00\x00\x00",
    b"#\x85\x0f\xf2\x00\x00\x00\x00",
    b"#\x85\x0f\xc0\x00\x00\x00\x00",
    b"#\x85\x0fT\x0fKAA",
    b"#\x85\x0fU\x0f&&{",
    b"#\x85\x0fV\x0c\xef\x0c\xef",
    b"#\x85\x0fW\x0c\xef\x0c\xeb",
    b"#\x85\x0f\xa1\x04\x03\x02\x08",
    b"#\x85\x0f\x90\x01\x0f\x01\x0f",
    b"#\x85\x0f\xb0\x10%\x00\x00",
    b'#\x85\x0f\xb1\x963"\x80',
    b"#\x85\x0f\x00\x00\x00\x00\x00",
    b"#\x85\x0f\xb3\x06@\x06@",
    b"#\x85\x0f\x00\x00\x00\x00\x00",
    b"#\x85\x0f\x00\x00\x00\x00\x00",
    b"#\x85\x0f\x00\x00\x00\x00\x00",
    b"#\x85\x0f\x00\x00\x00\x00\x00",
    b"#\x85\x0f\x00\x00\x00\x00\x00",
    b"#\x85\x0f\x00\x00\x00\x00\x00",
    b"#\x85\x0f\x00\x00\x00\x00\x00",
    b"#\x85\x0f\x00\x00\x00\x00\x00",
    b"#\x85\x0f\x00\x00\x00\x00\x00",
    b"#\x85\x0f\x00\x00\x00\x00\x00",
    b"#\x85\x0f\x00\x00\x00\x00\x00",
    b"MST+IMP=\xb0\x10%\x00\x00",
    b'MST+IMP=\xb1\x963"X',
    b"MST+IMP=\xb2\x00\x00\x00\x00",
    b"MST+IMP=\xb3\x06@\x06@",
    b"MST+IMP=\xb4\x00\x00\x00\x00",
    b"MST+IMP=\xb5\x00\x00\x00\x00",
    b"MST+IMP=\xb6\x00\x00\x00\x00",
    b"MST+IMP=\xb7\x00\x00\x00\x00",
    b"MST+IMP=\xb8\x00\x00\x00\x00",
    b"MST+IMP=\xb9\x00\x00\x00\x00",
    b"MST+IMP=\xba\x00\x00\x00\x00",
    b"MST+IMP=\xbb\x00\x00\x00\x00",
    b"MST+IMP=\xbc\x00\x00\x00\x00",
    b"MST+IMP=\xbd\x00\x00\x00\x00",
    b"MST+IMP=\xbe\x00\x00\x00\x00",
    b"MST+IMP=\xbf\x00\x00\x00\x00",
    b"U<\x80\x02\xb4?\xff\xff\xff\xff\x89",
    b"U}",
    b'U<\x85\x06\xb4 \x11"3O\xe9',
    b"U}\x85\x06\xf4\x0b\\\xff\xff\xff\x18",
    b'U<\x85\x06\xb4 \x11"3@\xf8',
    b"U}",
    b"\x85\x06\xf4\x02\x050\x81\x11\xb5",
    b"U<\x80\x02\xb4?\xff\xff\xff\xff\x89",
    b"U}",
    b'U<\x85\x06\xb4 \x11"3O\xe9',
    b"U}\x85\x06\xf4\x02\x05/\x81!\xa6",
    b'U<\x85\x06\xb4 \x11"3@\xf8',
    b"U}",
    b"\x85\x06\xf44\xff\xff\x08\x80\xc2",
    b"U<\x80\x02\xb4?\xff\xff\xff\xff\x89",
    b"U}",
    b'U<\x85\x06\xb4 \x11"3O\xe9',
    b"U}\x85\x06\xf4\x0c\x02\x80\xff\xff\xf0",
    b'U<\x85\x06\xb4 \x11"3@\xf8',
    b"U}",
    b"\x85\x06\xf4\x0ed\x00\x00\x00\r",
    b"U<\x80\x02\xb4?\xff\xff\xff\xff\x89",
    b"U}",
    b'U<\x85\x06\xb4 \x11"3O\xe9',
    b"U}\x85\x06\xf4\x0b\\\xff\xff\xff\x18",
    b'U<\x85\x06\xb4 \x11"3@\xf8',
    b"U}",
    b"\x85\x06\xf4\x0c\x02\x80\xff\xff\xf0",
    b"U<\x80\x02\xb4?\xff\xff\xff\xff\x89",
    b"U}",
    b'U<\x85\x06\xb4 \x11"3O\xe9',
    b"U}\x85\x06\xf4\x0ed\x00\x00\x00\r",
    b'U<\x85\x06\xb4 \x11"3@\xf8',
    b"U}",
    b"\x85\x06\xf4\x02\x050\x81\x11\xb5",
    b"U<\x80\x02\xb4?\xff\xff\xff\xff\x89",
    b"U}",
    b'U<\x85\x06\xb4 \x11"3O\xe9',
    b"U}\x85\x06\xf4\x07\x00\x00\x00\x96\xe1",
    b'U<\x85\x06\xb4 \x11"3@\xf8',
    b"U}",
    b"\x85\x06\xf4W\x0c\xf2\x0c\xf0,",
    b"U<\x80\x02\xb4?\xff\xff\xff\xff\x89",
    b"U}",
    b'U<\x85\x06\xb4 \x11"3O\xe9',
    b"U}\x85\x06\xf44\xff\xff\t:\x08",
    b'U<\x85\x06\xb4 \x11"3@\xf8',
    b"U}",
    b"\x85\x06\xf46\x07%\xff\xff\x1d",
    b"U<\x80\x02\xb4?\xff\xff\xff\xff\x89",
    b"MST+NET=\x85\x8f\x01\x05\x00\x08\x04\x03\x02\x05\x01",
    b"MST+NET=\x85\x00\x01\x05\x00\x08\x04\x03\x02\x05\x04",
    b'MST+DCO=\x11"3@',
    b"U<\x80\x02\xb4?\xff\xff\xff\xff\x89",
    b"U}",
    b'U<\x85\x06\xb4 \x11"3O\xe9',
    b"U}\x85\x06\xf4W\x0c\xef\x0c\xeb4",
    b'U<\x85\x06\xb4 \x11"3@\xf8',
    b"U}",
    b"\x85\x06\xf4\x02\x050\x81\x11\xb5",
    b"U<\x80\x02\xb4?\xff\xff\xff\xff\x89",
    b"U}",
    b'U<\x85\x06\xb4 \x11"3O\xe9',
    b"U}\x85\x06\xf4\x02\x051\x81$\xa1",
    b'U<\x85\x06\xb4 \x11"3@\xf8',
    b"U}",
    b"\x85\x06\xf4\x90\x02\x0f\x02\x0f\xcc",
    b"U<\x80\x02\xb4?\xff\xff\xff\xff\x89",
    b"U}",
    b'U<\x85\x06\xb4 \x11"3O\xe9',
    b"U}\x85\x06\xf46\x07\x16\xff\xff,",
    b'U<\x85\x06\xb4 \x11"3@\xf8',
    b"U}",
)

_PROTO_DEFS_MIN: Final[tuple[bytes, ...]] = (
    b"#\x85\x00\xf2\x00\x00\x00\x00",
    b"#\x85\x00\x02\x050\x81\x11",
    b"#\x85\x00V\x0c\xf3\x0c\xf4",
    b"#\x85\x00W\x0c\xf2\x0c\xf0",
    b"#\x85\x00\x0b\\\xff\xff\xff",
    b"#\x85\x00\x0c\x02\x80\xff\xff",
    b"#\x85\x00\x0ed\x00\x00\x00",
    b"#\x85\x00\xc0\x00\x00\x00\x00",
    b"#\x85\x006\x07%\xff\xff",
)

_RESULT_DEFS: Final[BMSSample] = {
    "pack_count": 2,
    "packs": [
        {
            "voltage": 13.28,
            "current": -2.74,
            "design_capacity": 150,
            "battery_level": 92,
            "temp_values": [TS(14.0)],
            "cycle_capacity": 1829,
            "battery_health": 100,
            "cell_voltages": [
                3.315,
                3.316,
                3.314,
                3.312,
            ],
            "delta_voltage": 0.004,
            "cell_count": 4,
        },
        {
            "voltage": 13.27,
            "current": -2.93,
            "design_capacity": 150,
            "battery_level": 92,
            "temp_values": [TS(14.0)],
            "cycle_capacity": 1814,
            "battery_health": 100,
            "cell_voltages": [
                3.311,
                3.311,
                3.311,
                3.307,
            ],
            "delta_voltage": 0.004,
            "cell_count": 4,
        },
    ],
    "battery_health": 100,
    "cell_voltages": [
        3.315,
        3.316,
        3.314,
        3.312,
        3.311,
        3.311,
        3.311,
        3.307,
    ],
    "cell_count": 4,
    "current": -5.67,
    "cycle_capacity": 3643,
    "design_capacity": 300,
    "delta_voltage": 0.004,
    "battery_level": 92,
    "voltage": 13.275,
    "battery_charging": False,
    "cycle_charge": 276,
    "power": -75.269,
    "runtime": 175238,
    "problem": False,
}
_RESULT_DEFS_MIN: Final[BMSSample] = {
    "pack_count": 1,
    "packs": [_RESULT_DEFS["packs"][0]],
    "battery_health": 100,
    "cell_voltages": _RESULT_DEFS["cell_voltages"][:4],
    "cell_count": 4,
    "current": -2.74,
    "cycle_capacity": 1829,
    "delta_voltage": 0.004,
    "battery_level": 92,
    "design_capacity": 150,
    "voltage": 13.28,
    "battery_charging": False,
    "cycle_charge": 138.0,
    "runtime": 181313,
    "power": -36.387,
    "problem": False,
}


class TestBasicBMS(BMSBasicTests):
    """Test the basic BMS functionality."""

    bms_class = BMS


class MockDBBleakClient(MockBleakClient):
    """Emulate a Dometic Büttner BMS BleakClient."""

    class _State(Enum):
        IDLE = auto()
        WAIT_CHC = auto()
        NOTIFY_CHB = auto()
        WAIT_CHB = auto()
        WAIT_AEN = auto()
        WAIT_NET = auto()
        WAIT_RDN = auto()
        RUNNING = auto()

    type ChannelT = Literal["chA", "chB", "chC"]

    DBSrv: Final = BleakGATTService(
        Self,
        0x0,
        "0000fefb-0000-1000-8000-00805f9b34fb",
    )

    _RESP: tuple[bytes, ...] = _PROTO_DEFS
    _chb_data: Final[bytes] = b"\x12"
    _chb_resp: Final[bytes] = b"\xff"
    _chc_data: Final[bytes] = b"\x9b\x00"

    _CHARACTERISTIC_DEFS: Final[dict[ChannelT, tuple[str, int]]] = {
        "chA": ("00000002-0000-1000-8000-008025000000", 21),
        "chB": ("00000004-0000-1000-8000-008025000000", 22),
        "chC": ("0000000a-0000-1000-8000-008025000000", 23),
    }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize MockDometicBBleakClient."""
        super().__init__(*args, **kwargs)
        self._idx: int = 0
        self._state: MockDBBleakClient._State = self._State.IDLE
        self._cbs: dict[
            MockDBBleakClient.ChannelT,
            Callable[[BleakGATTCharacteristic, bytearray], Awaitable[None]],
        ] = {}
        self._tasks: dict[MockDBBleakClient.ChannelT, asyncio.Task[None]] = {}

        self._characteristics: Final[
            dict[
                MockDBBleakClient.ChannelT,
                BleakGATTCharacteristic,
            ]
        ] = {
            channel: BleakGATTCharacteristic(
                self,
                handle,
                uuid,
                ["notify"],
                lambda: BMS.BLE_MAX_ATTR_SIZE,
                self.DBSrv,
            )
            for channel, (uuid, handle) in self._CHARACTERISTIC_DEFS.items()
        }

    async def _notify(
        self,
        channel: ChannelT,
        data: Buffer,
    ) -> None:
        """Send a notification through a registered channel."""
        callback = self._cbs.get(channel)
        assert callback is not None, f"No callback registered for {channel}"

        await callback(
            self._characteristics[channel],
            bytearray(data),
        )

    async def _send_info(self) -> None:
        """Continuously send protocol information over channel A."""
        assert self._cbs.get("chA") is not None

        try:
            while True:
                response: bytes = self._RESP[self._idx]

                for offset in range(0, len(response), BT_FRAME_SIZE):
                    await self._notify(
                        "chA",
                        response[offset : offset + BT_FRAME_SIZE],
                    )

                self._idx = (self._idx + 1) % len(self._RESP)

                if not self._idx:
                    await asyncio.sleep(0)
        except asyncio.CancelledError:
            return

    async def write_gatt_char(
        self,
        char_specifier: BleakGATTCharacteristic | int | str | UUID,
        data: Buffer,
        response: bool | None = None,
    ) -> None:
        """Issue write command to GATT."""
        await super().write_gatt_char(char_specifier, data, response)

        assert isinstance(char_specifier, str)

        characteristic = char_specifier[4:8]
        payload = bytes(data)

        if (
            self._state == self._State.WAIT_CHC
            and characteristic == "0009"
            and payload == self._chc_data
        ):
            self._state = self._State.NOTIFY_CHB
            return

        if (
            self._state == self._State.WAIT_CHB
            and characteristic == "0003"
            and payload == self._chb_resp
        ):
            self._state = self._State.WAIT_AEN
            return

        if (
            self._state == self._State.WAIT_AEN
            and characteristic == "0001"
            and payload == b"APP+AEN"
        ):
            self._state = self._State.WAIT_NET
            await self._notify("chA", b"MST+AEN")
            return

        if (
            self._state == self._State.WAIT_NET
            and characteristic == "0001"
            and payload == b"APP+NET"
        ):
            self._state = self._State.WAIT_RDN
            await self._notify("chA", b"MST+NET=mock")
            return

        if (
            self._state in (self._State.WAIT_RDN, self._State.RUNNING)
            and characteristic == "0001"
            and payload == b"APP+RDN=1"
        ):
            self._state = self._State.RUNNING
            await self._notify("chA", b'MST+DCO=\x11"3@')

            task: asyncio.Task[None] | None = self._tasks.get("chA")
            if task is None or task.done():
                self._tasks["chA"] = asyncio.create_task(
                    self._send_info(),
                    name="mock-db-chA",
                )
            return
        if self._state == self._State.RUNNING and (
            (characteristic == "0001" and payload == b"APP+NET")
            or (characteristic == "0003" and payload in (b"\xff", b"\xdf"))
        ):  # keep alive message
            return

        pytest.fail(f"write init sequence incorrect ({self._state=})")

    async def _mock_chB(self) -> None:
        """Send the initial notification over channel B."""
        self._state = self._State.WAIT_CHB
        await self._notify("chB", self._chb_data)

    async def _mock_chC(self) -> None:
        """Send the initial notification over channel C."""
        self._state = self._State.WAIT_CHC
        await self._notify("chC", self._chc_data)

    async def start_notify(
        self,
        char_specifier: BleakGATTCharacteristic | int | str | UUID,
        callback: Callable[
            [BleakGATTCharacteristic, bytearray],
            None | Awaitable[None],
        ],
        **kwargs: Any,
    ) -> None:
        """Mock start_notify."""
        characteristic = str(char_specifier)[4:8]

        assert callable(callback) and inspect.iscoroutinefunction(
            callback
        ), "callback must be an async function"

        self._enabled_notify.add(char_specifier)

        if self._state == self._State.WAIT_AEN and characteristic == "0002":
            self._cbs["chA"] = callback
            return

        if self._state == self._State.NOTIFY_CHB and characteristic == "0004":
            # Register the callback before creating the task to avoid a race.
            self._cbs["chB"] = callback
            self._tasks["chB"] = asyncio.create_task(
                self._mock_chB(),
                name="mock-db-chB",
            )
            return

        if self._state == self._State.IDLE and characteristic == "000a":
            # Register the callback before creating the task to avoid a race.
            self._cbs["chC"] = callback
            self._tasks["chC"] = asyncio.create_task(
                self._mock_chC(),
                name="mock-db-chC",
            )
            return

        pytest.fail(f"notify init sequence incorrect ({self._state=})")

    async def disconnect(self) -> None:
        """Mock disconnect and wait for notification tasks."""

        tasks: Final = tuple(self._tasks.values())
        for task in tasks:
            if not task.done():
                LOGGER.debug("cancelling task=%r", task)
                task.cancel()

        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task

        await super().disconnect()
        self._state = self._State.IDLE
        self._tasks.clear()
        self._cbs.clear()


async def test_update(
    monkeypatch: pytest.MonkeyPatch, patch_bleak_client, keep_alive_fixture: bool
) -> None:
    """Test Dometic Büttner BMS data update."""

    monkeypatch.setattr(MockDBBleakClient, "_RESP", _PROTO_DEFS)
    patch_bleak_client(MockDBBleakClient)

    bms = BMS(generate_ble_device(), BMSConfig(keep_alive=keep_alive_fixture))

    assert await bms.async_update() == _RESULT_DEFS

    # query again to check already connected state
    await bms.async_update()
    assert bms.is_connected is keep_alive_fixture

    await bms.disconnect()


async def test_incomplete_first_update(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
) -> None:
    """Test Dometic Büttner BMS data update with missing design capacity at beginning."""

    monkeypatch.setattr(
        MockDBBleakClient, "_RESP", _PROTO_DEFS_MIN
    )  # patch minimal set without design capacity
    patch_bleak_client(MockDBBleakClient)

    bms = BMS(generate_ble_device(), BMSConfig())

    with pytest.raises(ValueError, match="BMS data incomplete."):
        await bms.async_update()

    await bms.disconnect()


async def test_inc_update(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
) -> None:
    """Test Dometic Büttner BMS incremental update (second without design capacity)."""

    patch_bleak_client(MockDBBleakClient)

    bms = BMS(generate_ble_device(), BMSConfig())

    assert await bms.async_update() == _RESULT_DEFS
    monkeypatch.setattr(
        MockDBBleakClient, "_RESP", _PROTO_DEFS_MIN
    )  # patch minimal set without design capacity
    assert await bms.async_update() == _RESULT_DEFS_MIN
    await bms.disconnect()


@pytest.mark.parametrize("complete_set", [True, False])
async def test_bms_disconnect(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    complete_set: bool,
) -> None:
    """Test Dometic Büttner BMS data update."""

    monkeypatch.setattr(
        MockDBBleakClient,
        "_RESP",
        (
            [*_PROTO_DEFS_MIN, b"#\x85\x00\x07\x00\x00\x00\x96", b"+++"]
            if complete_set
            else [*_PROTO_DEFS_MIN[:-1], b"+++"]
        ),
    )
    monkeypatch.setattr(BMS, "_GATHER_TIMEOUT", 1e-3)
    patch_bleak_client(MockDBBleakClient)

    bms = BMS(generate_ble_device(), BMSConfig())

    if complete_set:
        assert await bms.async_update() == _RESULT_DEFS_MIN
        assert bms.is_connected is True
        assert (
            await bms.async_update() == _RESULT_DEFS_MIN
        )  # BMS disconnects on next call
    else:
        with pytest.raises(TimeoutError):
            await bms.async_update()
        with pytest.raises(ValueError, match="BMS data incomplete"):
            await bms.async_update()

    assert bms.is_connected is False


class MockDBBleakClientBrokenSender(MockDBBleakClient):
    """Mock that delivers a notification from an unknown-UUID characteristic."""

    async def _mock_chB(self) -> None:
        self._state = self._State.WAIT_CHB
        await self._notify("chB", bytearray(b""))
        alien_char = BleakGATTCharacteristic(
            self, 99, "12345678", ["notify"], lambda: BMS.BLE_MAX_ATTR_SIZE, self.DBSrv
        )  # unknown UUID -> case _:
        await self._cbs["chB"](alien_char, bytearray(b"\x12"))
        await self._notify("chB", self._chb_data)  # real data continues init


async def test_alive_loop_running(
    monkeypatch: pytest.MonkeyPatch, patch_bleak_client
) -> None:
    """Test that the keep-alive loop actually sends its keep-alive messages."""
    monkeypatch.setattr(MockDBBleakClient, "_RESP", _PROTO_DEFS)
    monkeypatch.setattr(BMS, "ALIVE_INTERVAL", 0.0)
    patch_bleak_client(MockDBBleakClient)

    written: set[tuple[str, bytes]] = set()
    orig_write: Final = MockDBBleakClient.write_gatt_char

    async def _watch_write(self, char_specifier, data, response=None) -> None:
        written.add((str(char_specifier)[4:8], bytes(data)))
        await orig_write(self, char_specifier, data, response)

    monkeypatch.setattr(MockDBBleakClient, "write_gatt_char", _watch_write)

    bms = BMS(generate_ble_device(), BMSConfig(keep_alive=True))

    assert await bms.async_update() == _RESULT_DEFS
    assert bms.is_connected is True

    written.clear()  # ignore init-sequence writes

    # yield control so loop performs its keep-alive exchange (APP+NET write + ch_b_tx write)
    for _ in range(3):
        await asyncio.sleep(0)

    # confirm both keep-alive writes actually happened
    assert ("0001", b"APP+NET") in written
    assert ("0003", b"\xff") in written
    assert ("0003", b"\xdf") in written

    await bms.disconnect()
    assert bms.is_connected is False


async def test_keep_alive_handler_broken_sender(
    monkeypatch: pytest.MonkeyPatch,
    patch_bleak_client,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test _keep_alive_handler case _: for notification from unknown UUID."""
    monkeypatch.setattr(MockDBBleakClient, "_RESP", _PROTO_DEFS)
    patch_bleak_client(MockDBBleakClientBrokenSender)

    bms = BMS(generate_ble_device(), BMSConfig())
    with caplog.at_level(DEBUG):
        await bms.async_update()
    assert "unknown notification sender" in caplog.text
    assert "empty notification" in caplog.text
    await bms.disconnect()


async def test_update_with_preset_event(
    monkeypatch: pytest.MonkeyPatch, patch_bleak_client
) -> None:
    """Test _async_update skips data request when msg_event is already set."""
    monkeypatch.setattr(MockDBBleakClient, "_RESP", _PROTO_DEFS)
    patch_bleak_client(MockDBBleakClient)

    bms = BMS(generate_ble_device(), BMSConfig(keep_alive=True))
    await bms.async_update()
    # Yield twice so _send_info fills _data_final and sets _msg_event
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    # Second update finds _msg_event pre-set and skips the APP+RDN=1 request
    await bms.async_update()
    await bms.disconnect()
