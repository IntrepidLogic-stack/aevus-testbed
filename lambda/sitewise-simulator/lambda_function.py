import math
import random
import time
from datetime import datetime

import boto3

sw = boto3.client('iotsitewise', region_name='us-east-1')
_s = {}
ASSETS = {
    "3d266802-c081-43b0-bbd3-c03c3a3fa516": [
        ("51f06d34-7486-4c46-9773-b326a260903f", 280.0, 8.0),
        ("940b9183-c709-40c7-876f-778968c19772", 315.0, 6.0),
        ("83c3169a-b424-4c39-b55d-1727def4c44a", 142.0, 4.0),
        ("5f1f08f6-ea44-4cb2-9b1a-f01e3b051fd1", 0.2, 0.15),
        ("4a15460b-3291-4492-bf30-822c4679c8be", 2.8, 0.3),
    ],
    "ed7c7a98-613c-4e64-ab04-4aa1b218a48a": [
        ("02e9571b-25be-49bf-84f1-7a0862744e23", 185.0, 5.0),
        ("6b038c0f-aab7-4894-a3fb-66d0dc691031", 95.0, 3.0),
        ("c3c2a9ca-fe4f-4243-9ee6-68846f9725ec", 42.0, 8.0),
        ("47578da3-6812-42dc-985c-784724cb2dff", 1.2, 0.2),
        ("0179e2c3-096a-43fd-9f74-0c2479634595", 128.0, 3.0),
    ],
    "6163245a-a86b-4c4a-9925-4c6daa2f4857": [
        ("2ce823d9-5f27-4efb-9cba-e2031afe46a0", 145.0, 5.0),
        ("d0fa02b9-1b96-4aef-bae7-2a398f65e042", 165.0, 4.0),
        ("f9996c58-4096-4ee8-ad9f-7e91f90683f7", 1780.0, 30.0),
        ("2708fc55-c2bb-4e02-8203-c90450c1e4ed", 0.35, 0.1),
        ("57718176-0734-4d94-993a-d19883739257", 185.0, 5.0),
        ("49737816-f420-404d-a673-9a3c2a1d6bd2", 42.0, 2.0),
    ],
    "631d79aa-7419-44db-9f2e-832866cfd00f": [
        ("ad5c1c78-05a6-417a-a7d8-60df3ad69490", 72.0, 5.0),
        ("36942bc0-8666-416c-a416-be0d99353066", 35.0, 3.0),
        ("7a6ff8d3-21a5-4ec5-a87c-c1578e590544", 88.0, 2.0),
        ("bb1c7f6b-a1ef-447e-b55e-b4149172c3d3", 14.2, 0.8),
    ],
    "209a6441-5170-4285-a10c-3de3e9e9274f": [
        ("0b06634e-7551-4dbd-9cf4-4817567f027d", 2.4, 0.3),
        ("fcc9881e-a2c6-410d-896c-b56bc5ff95d8", 42.0, 4.0),
        ("fc4abcb7-a23d-4c69-bb10-2e4bbd51267b", 0.8, 0.2),
        ("c4adcd7f-f2ac-4b04-b9d9-99e29162d5e8", 14250.0, 20.0),
    ],
    "892fce89-b2c6-4fc2-9e01-4b636b0fce21": [
        ("f08a6ebc-df93-427e-ab66-98e3884e650d", -42.0, 3.0),
        ("ae41fe68-9ecd-4a42-886d-0f1a9a41a098", 12.1, 0.2),
        ("95c6b26f-2f57-43c1-b829-bad33463dd62", 18.5, 3.0),
        ("862c0309-4ff8-4220-b3ca-659f9d704d4b", 720.0, 1.0),
    ],
    "0dfbd56a-f1a0-4117-8ef2-1cf3bdef9369": [
        ("f08a6ebc-df93-427e-ab66-98e3884e650d", -38.0, 3.0),
        ("ae41fe68-9ecd-4a42-886d-0f1a9a41a098", 11.8, 0.2),
        ("95c6b26f-2f57-43c1-b829-bad33463dd62", 16.2, 2.5),
        ("862c0309-4ff8-4220-b3ca-659f9d704d4b", 680.0, 1.0),
    ],
}
def lambda_handler(event, context):
    now = int(time.time())
    entries = []
    for aid, props in ASSETS.items():
        for pid, base, var in props:
            k = f"{aid}:{pid}"
            if k not in _s:
                _s[k] = base
            cur = _s[k]
            drift = random.gauss(0, var * 0.05)
            revert = (base - cur) * 0.02
            hour = datetime.utcnow().hour
            diurnal = math.sin((hour - 6) * math.pi / 12) * var * 0.1
            _s[k] = cur + drift + revert + diurnal * 0.01
            entries.append({
                'entryId': f"{aid[:8]}-{pid[:8]}-{now}",
                'assetId': aid, 'propertyId': pid,
                'propertyValues': [{'value': {'doubleValue': round(_s[k], 2)}, 'timestamp': {'timeInSeconds': now}, 'quality': 'GOOD'}]
            })
    for i in range(0, len(entries), 10):
        try:
            sw.batch_put_asset_property_value(entries=entries[i:i+10])
        except Exception as e:
            print(f"Batch {i} error: {e}")
    return {'statusCode': 200, 'body': f'{len(entries)} values published'}
