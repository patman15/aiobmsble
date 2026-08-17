"""Test the Dometic Büttner BMS implementation."""

import asyncio
from collections.abc import Awaitable, Buffer, Callable
import contextlib
from enum import Enum, auto
import inspect
from typing import Any, Final, Literal
from uuid import UUID

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.service import BleakGATTService
import pytest

from aiobmsble import BMSConfig, BMSSample
from aiobmsble.bms.dometic_bms import BMS
from tests.bluetooth import generate_ble_device
from tests.conftest import LOGGER, MockBleakClient
from tests.test_basebms import BMSBasicTests

BT_FRAME_SIZE = 32

_PROTO_DEFS: Final[list[bytes]] = [
    # init sequence:
    #    b"\x9b\x00",
    #    b"\x12",
    #    b"MST+AEN",
    #    b"MST+NET=\x85\x8f\x01\x05\x00\x08\x04\x03\x02\x05\x01",
    #    b"MST+NET=\x85\x00\x01\x05\x00\x08\x04\x03\x02\x05\x04",
    #    b'MST+DCO=\x11"3@',
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
    b"\x85\x06\xf4\xf2\x00\x00\x00\x00\x8c",
    b"U<\x80\x02\xb4?\xff\xff\xff\xff\x89",
    b"U}",
    b'U<\x85\x06\xb4 \x11"3O\xe9',
    b"U}\x85\x06\xf4\x02\x051\x81$\xa1",
    b'U<\x85\x06\xb4 \x11"3@\xf8',
    b"U}",
    b"\x85\x06\xf45\nW\x07X\x89",
    b"U<\x80\x02\xb4?\xff\xff\xff\xff\x89",
    b"U}",
    b'U<\x85\x06\xb4 \x11"3O\xe9',
    b"U}\x85\x06\xf4\x02\x050\x81$\xa2",
    b'U<\x85\x06\xb4 \x11"3@\xf8',
    b"U}",
    b"\x85\x06\xf4\xf1\x00\x00\x00\x00\x8d",
    b"U<\x80\x02\xb4?\xff\xff\xff\xff\x89",
    b"U}",
    b'U<\x85\x06\xb4 \x11"3O\xe9',
    b"U}\x85\x06\xf4\x90\x01\x0f\x01\x0f\xce",
    b'U<\x85\x06\xb4 \x11"3@\xf8',
    b"U}",
    b"\x85\x06\xf4\x02\x051\x81\x11\xb4",
    b"U<\x80\x02\xb4?\xff\xff\xff\xff\x89",
    b"U}",
    b'U<\x85\x06\xb4 \x11"3O\xe9',
    b"U}\x85\x06\xf4\xb0\x10%\x00\x00\x99",
    b'U<\x85\x06\xb4 \x11"3@\xf8',
    b"U}",
    b"\x85\x06\xf4\xa1\x04\x03\x02\x08\xcc",
    b"U<\x80\x02\xb4?\xff\xff\xff\xff\x89",
    b"U}",
    b'U<\x85\x06\xb4 \x11"3O\xe9',
    b"U}\x85\x06\xf4\x02\x050\x81&\xa0",
    b'U<\x85\x06\xb4 \x11"3@\xf8',
    b"U}",
    b"\x85\x06\xf4\x0b\\\xff\xff\xff\x18",
    b"U<\x80\x02\xb4?\xff\xff\xff\xff\x89",
    b"U}",
    b'U<\x85\x06\xb4 \x11"3O\xe9',
    b"U}\x85\x06\xf4\xa1\x04\x03\x02\x08\xcc",
    b'U<\x85\x06\xb4 \x11"3@\xf8',
    b"U}",
    b"\x85\x06\xf4\x02\x051\x81\x11\xb4",
    b"U<\x80\x02\xb4?\xff\xff\xff\xff\x89",
    b"U}",
    b'U<\x85\x06\xb4 \x11"3O\xe9',
    b"U}\x85\x06\xf4\x02\x05/\x81$\xa3",
    b'U<\x85\x06\xb4 \x11"3@\xf8',
    b"U}",
    b"\x85\x06\xf4\x02\x050\x81\x11\xb5",
    b"U<\x80\x02\xb4?\xff\xff\xff\xff\x89",
    b"U}",
    b'U<\x85\x06\xb4 \x11"3O\xe9',
    b"U}\x85\x06\xf4T\x0fKAAN",
    b'U<\x85\x06\xb4 \x11"3@\xf8',
    b"U}",
    b"\x85\x06\xf4V\x0c\xf3\x0c\xf5",
    b"U<\x80\x02\xb4?\xff\xff\xff\xff\x89",
    b"U}",
    b'U<\x85\x06\xb4 \x11"3O\xe9',
    b"U}\x85\x06\xf4\xf1\x00\x00\x00\x00\x8d",
    b'U<\x85\x06\xb4 \x11"3@\xf8',
    b"U}",
    b"\x85\x06\xf4\x0c\x02\x80\xff\xff\xf0",
    b"U<\x80\x02\xb4?\xff\xff\xff\xff\x89",
    b"U}",
    b'U<\x85\x06\xb4 \x11"3O\xe9',
    b"U}\x85\x06\xf4\x07\x00\x00\x00\x96\xe1",
    b'U<\x85\x06\xb4 \x11"3@\xf8',
    b"U}",
    b"\x85\x06\xf44\xff\xff\x08\x81\xc1",
    b"U<\x80\x02\xb4?\xff\xff\xff\xff\x89",
    b"U}",
    b'U<\x85\x06\xb4 \x11"3O\xe9',
    b"U}\x85\x06\xf4\x02\x05-\x81$\xa5",
    b'U<\x85\x06\xb4 \x11"3@\xf8',
    b"U}",
    b"\x85\x06\xf4\x07\x00\x00\x00\x96\xe1",
    b"U<\x80\x02\xb4?\xff\xff\xff\xff\x89",
    b"U}",
    b'U<\x85\x06\xb4 \x11"3O\xe9',
    b"U}\x85\x06\xf4\xc0\x00\x00\x00\x00\xbe",
    b'U<\x85\x06\xb4 \x11"3@\xf8',
    b"U}",
    b"\x85\x06\xf4\x02\x050\x81\x11\xb5",
    b"U<\x80\x02\xb4?\xff\xff\xff\xff\x89",
    b"U}",
    b'U<\x85\x06\xb4 \x11"3O\xe9',
    b"U}\x85\x06\xf4\xb3\x06@\x06@?",
    b'U<\x85\x06\xb4 \x11"3@\xf8',
    b"U}",
    b"\x85\x06\xf4\x02\x050\x81\x11\xb5",
    b"U<\x80\x02\xb4?\xff\xff\xff\xff\x89",
    b"U}",
    b'U<\x85\x06\xb4 \x11"3O\xe9',
    b"U}\x85\x06\xf4\x02\x050\x81$\xa2",
    b'U<\x85\x06\xb4 \x11"3@\xf8',
    b"U}",
    b"\x85\x06\xf46\x07%\xff\xff\x1d",
    b"U<\x80\x02\xb4?\xff\xff\xff\xff\x89",
    b"U}",
    b'U<\x85\x06\xb4 \x11"3O\xe9',
    b"U}\x85\x06\xf44\xff\xff\t9\t",
    b'U<\x85\x06\xb4 \x11"3@\xf8',
    b"U}",
    b"\x85\x06\xf4`@\x00\x04\x00\xda",
    b"U<\x80\x02\xb4?\xff\xff\xff\xff\x89",
    b"U}",
    b'U<\x85\x06\xb4 \x11"3O\xe9',
    b"U}\x85\x06\xf4\x02\x05/\x81&\xa1",
    b'U<\x85\x06\xb4 \x11"3@\xf8',
    b"U}",
    b"\x85\x06\xf45\nW\x07X\x89",
    b"U<\x80\x02\xb4?\xff\xff\xff\xff\x89",
    b"U}",
    b'U<\x85\x06\xb4 \x11"3O\xe9',
    b"U}\x85\x06\xf46\x07\x16\xff\xff,",
    b'U<\x85\x06\xb4 \x11"3@\xf8',
    b"U}",
    b"\x85\x06\xf4\x0b\\\xff\xff\xff\x18",
    b"U<\x80\x02\xb4?\xff\xff\xff\xff\x89",
    b"U}",
    b'U<\x85\x06\xb4 \x11"3O\xe9',
    b"U}\x85\x06\xf45\n\xac\x07l ",
    b'U<\x85\x06\xb4 \x11"3@\xf8',
    b"U}",
    b"\x85\x06\xf4\x07\x00\x00\x00\x96\xe1",
    b"U\x99",
    b"U\x97",
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
    b"U}\x85\x06\xf4\x02\x05-\x81!\xa8",
    b'U<\x85\x06\xb4 \x11"3@\xf8',
    b"U}",
    b"\x85\x06\xf4\x0b\\\xff\xff\xff\x18",
    b"U<\x80\x02\xb4?\xff\xff\xff\xff\x89",
    b"U}",
    b'U<\x85\x06\xb4 \x11"3O\xe9',
    b"U}\x85\x06\xf4\x0b\\\xff\xff\xff\x18",
    b'U<\x85\x06\xb4 \x11"3@\xf8',
    b"U}",
    b"\x85\x06\xf4\xf2\x00\x00\x00\x00\x8c",
    b"U<\x80\x02\xb4?\xff\xff\xff\xff\x89",
    b"U}",
    b'U<\x85\x06\xb4 \x11"3O\xe9',
    b"U}\x85\x06\xf4\x02\x05/\x81$\xa3",
    b'U<\x85\x06\xb4 \x11"3@\xf8',
    b"U}",
    b"\x85\x06\xf4\xc0\x00\x00\x00\x00\xbe",
    b"U<\x80\x02\xb4?\xff\xff\xff\xff\x89",
    b"U}",
    b'U<\x85\x06\xb4 \x11"3O\xe9',
    b"U}\x85\x06\xf4\x0c\x02\x80\xff\xff\xf0",
    b'U<\x85\x06\xb4 \x11"3@\xf8',
    b"U}",
    b"\x85\x06\xf4\x0b\\\xff\xff\xff\x18",
    b"U<\x80\x02\xb4?\xff\xff\xff\xff\x89",
    b"U}",
    b'U<\x85\x06\xb4 \x11"3O\xe9',
    b'U}\x85\x06\xf4\xb1\x963"\x80a',
    b"+++",
    b"+++",
]

_RESULT_DEFS: Final[BMSSample] = {
    "battery_charging": False,
    "battery_level": 92,
    "battery_health": 100,
    "cell_count": 4,
    "cell_voltages": [3.315, 3.316, 3.314, 3.312],
    "cycle_charge": 138.0,
    "cycle_capacity": 1829,
    "delta_voltage": 0.004,
    "design_capacity": 150,
    "voltage": 13.28,
    "current": -2.74,
    "power": -36.387,
    "runtime": 181313,
    "temperature": 14.0,
    "problem": False,
}


class TestBasicBMS(BMSBasicTests):
    """Test the basic BMS functionality."""

    bms_class = BMS


class MockDometicBBleakClient(MockBleakClient):
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

    _RESP: list[bytes] = _PROTO_DEFS
    _chb_data: Final[bytes] = b"\x12"
    _chb_resp: Final[bytes] = b"\xff"
    _chc_data: Final[bytes] = b"\x9b\x00"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize MockDometicBBleakClient."""
        super().__init__(*args, **kwargs)
        self._idx: int = 0
        self._state: MockDometicBBleakClient._State = self._State.IDLE
        self._cbs: dict[
            Literal["chA", "chB", "chC"],
            Callable[[BleakGATTCharacteristic, bytearray], Awaitable[None]],
        ] = {}
        self._tasks: dict[Literal["chA", "chB", "chC"], asyncio.Task[None]] = {}

    async def _send_info(self) -> None:
        assert self._cbs.get("chA") is not None
        while True:
            for notify_data in [
                self._RESP[self._idx][i : i + BT_FRAME_SIZE]
                for i in range(0, len(self._RESP[self._idx]), BT_FRAME_SIZE)
            ]:
                await self._cbs["chA"](
                    BleakGATTCharacteristic(
                        self,
                        0x1,
                        "00000002-0000-1000-8000-008025000000",
                        ["notify"],
                        lambda: 22,
                        BleakGATTService(
                            self, 0x0, "0000fefb-0000-1000-8000-00805f9b34fb"
                        ),
                    ),
                    bytearray(notify_data),
                )
            self._idx = (self._idx + 1) % len(self._RESP)
            if not self._idx:
                await asyncio.sleep(0)

    async def write_gatt_char(
        self,
        char_specifier: BleakGATTCharacteristic | int | str | UUID,
        data: Buffer,
        response: bool | None = None,
    ) -> None:
        """Issue write command to GATT."""
        await super().write_gatt_char(char_specifier, data, response)
        assert isinstance(char_specifier, str)
        if (
            self._state == self._State.WAIT_CHC
            and char_specifier[4:8] == "0009"
            and bytes(data) == self._chc_data
        ):
            self._state = self._State.NOTIFY_CHB
            return
        if (
            self._state == self._State.WAIT_CHB
            and char_specifier[4:8] == "0003"
            and bytes(data) == self._chb_resp
        ):
            self._state = self._State.WAIT_AEN
            return
        if (
            self._state == self._State.WAIT_AEN
            and char_specifier[4:8] == "0001"
            and bytes(data) == b"APP+AEN"
        ):
            self._state = self._State.WAIT_NET
            await self._cbs["chA"](
                BleakGATTCharacteristic(
                    self,
                    0x1,
                    "00000002-0000-1000-8000-008025000000",
                    ["notify"],
                    lambda: 22,
                    BleakGATTService(self, 0x0, "0000fefb-0000-1000-8000-00805f9b34fb"),
                ),
                bytearray(b"MST+AEN"),
            )
            return
        if (
            self._state == self._State.WAIT_NET
            and char_specifier[4:8] == "0001"
            and bytes(data) == b"APP+NET"
        ):
            self._state = self._State.WAIT_RDN
            await self._cbs["chA"](
                BleakGATTCharacteristic(
                    self,
                    0x1,
                    "00000002-0000-1000-8000-008025000000",
                    ["notify"],
                    lambda: 22,
                    BleakGATTService(self, 0x0, "0000fefb-0000-1000-8000-00805f9b34fb"),
                ),
                bytearray(b"MST+NET=mock"),
            )
            return
        if (
            (self._state in (self._State.WAIT_RDN, self._State.RUNNING))
            and char_specifier[4:8] == "0001"
            and bytes(data) == b"APP+RDN=1"
        ):
            self._state = self._State.RUNNING
            await self._cbs["chA"](
                BleakGATTCharacteristic(
                    self,
                    0x1,
                    "00000002-0000-1000-8000-008025000000",
                    ["notify"],
                    lambda: 22,
                    BleakGATTService(self, 0x0, "0000fefb-0000-1000-8000-00805f9b34fb"),
                ),
                bytearray(b'MST+DCO=\x11"3@'),
            )
            self._tasks["chA"] = asyncio.create_task(self._send_info())
            return
        pytest.fail(f"write init sequence incorrect ({self._state=})")

    async def _mock_chB(self) -> None:
        assert self._cbs.get("chB") is not None
        self._state = self._State.WAIT_CHB
        await self._cbs["chB"](
            BleakGATTCharacteristic(
                self,
                0x1,
                "00000004-0000-1000-8000-008025000000",
                ["notify"],
                lambda: 21,
                BleakGATTService(self, 0x0, "0000fefb-0000-1000-8000-00805f9b34fb"),
            ),
            bytearray(self._chb_data),
        )

    async def _mock_chC(self) -> None:
        assert self._cbs.get("chC") is not None
        self._state = self._State.WAIT_CHC
        await self._cbs["chC"](
            BleakGATTCharacteristic(
                self,
                0x1,
                "0000000a-0000-1000-8000-008025000000",
                ["notify"],
                lambda: 22,
                BleakGATTService(self, 0x0, "0000fefb-0000-1000-8000-00805f9b34fb"),
            ),
            bytearray(self._chc_data),
        )

    async def start_notify(
        self,
        char_specifier: BleakGATTCharacteristic | int | str | UUID,
        callback: Callable[
            [BleakGATTCharacteristic, bytearray], None | Awaitable[None]
        ],
        **kwargs,
    ) -> None:
        """Mock start_notify."""
        characteristic: Final[str] = str(char_specifier)[4:8]
        assert callable(callback) and inspect.iscoroutinefunction(
            callback
        ), "callback must be an async function"
        self._enabled_notify.add(char_specifier)

        if self._state == self._State.WAIT_AEN and characteristic == "0002":
            self._cbs["chA"] = callback
            return
        if self._state == self._State.NOTIFY_CHB and characteristic == "0004":  # chB
            self._tasks["chB"] = asyncio.create_task(self._mock_chB())
            self._cbs["chB"] = callback
            return
        if self._state == self._State.IDLE and characteristic == "000a":  # chC
            self._tasks["chC"] = asyncio.create_task(self._mock_chC())
            self._cbs["chC"] = callback
            return

        pytest.fail(f"notify init sequence incorrect ({self._state=})")

    async def disconnect(self) -> None:
        """Mock disconnect and wait for send task."""
        for task in self._tasks.values():
            LOGGER.debug(f"cancelling {task=}")
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._state = self._State.IDLE
        self._tasks.clear()
        self._cbs.clear()
        await super().disconnect()


async def test_update(
    monkeypatch: pytest.MonkeyPatch, patch_bleak_client, keep_alive_fixture: bool
) -> None:
    """Test Dometic Büttner BMS data update."""

    monkeypatch.setattr(MockDometicBBleakClient, "_RESP", _PROTO_DEFS)
    patch_bleak_client(MockDometicBBleakClient)

    bms = BMS(generate_ble_device(), BMSConfig(keep_alive=keep_alive_fixture))

    assert await bms.async_update() == _RESULT_DEFS

    # query again to check already connected state
    await bms.async_update()
    assert bms.is_connected is keep_alive_fixture

    await bms.disconnect()


# @pytest.mark.parametrize(
#     ("wrong_response"),
#     [
#         b"",
#         b"\x00\x72\x5e\x64\x00\x00\x01\xa4\xbe\xcc\xcc\xcd\x41\x62\x89\xc5\x00\x00\x00",
#     ],
#     ids=["empty", "too_short"],
# )
# async def test_invalid_response(
#     monkeypatch: pytest.MonkeyPatch,
#     patch_bleak_client,
#     patch_bms_timeout,
#     wrong_response: bytes,
# ) -> None:
#     """Test data up date with BMS returning invalid data."""

#     patch_bms_timeout("dometic_bms")
#     monkeypatch.setattr(MockDometicBBleakClient, "_RESP", bytearray(wrong_response))
#     patch_bleak_client(MockDometicBBleakClient)

#     bms = BMS(generate_ble_device())

#     result: BMSSample = {}
#     with pytest.raises(TimeoutError):
#         result = await bms.async_update()

#     assert not result
#     await bms.disconnect()


# @pytest.mark.parametrize(
#     ("problem_response"),
#     [
#         b"\x00\x74\x5e\x64\x00\x00\x01\xa4\xbe\xcc\xcc\xcd\x41\x62\x89\xc5\x00\x00\x00\x00",
#         b"\x00\x72\x5e\x64\x00\x00\x01\xa4\xbe\xcc\xcc\xcd\x41\x62\x89\xc5\x00\x00\x00\x00",
#     ],
#     ids=["chrg_warning", "dischrg_warning"],
# )
# async def test_problem_response(
#     monkeypatch: pytest.MonkeyPatch, patch_bleak_client, problem_response
# ) -> None:
#     """Test data update with BMS returning error flags."""

#     monkeypatch.setattr(MockDometicBBleakClient, "_RESP", bytearray(problem_response))

#     patch_bleak_client(MockDometicBBleakClient)

#     bms = BMS(generate_ble_device())

#     result: BMSSample = await bms.async_update()
#     assert result == _RESULT_DEFS | {"problem": True, "problem_code": 1}

#     await bms.disconnect()
