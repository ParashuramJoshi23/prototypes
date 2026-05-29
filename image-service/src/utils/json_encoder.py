import json
from decimal import Decimal


class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return int(obj) if obj == obj.to_integral_value() else float(obj)
        return super().default(obj)


def dumps(obj) -> str:
    return json.dumps(obj, cls=DecimalEncoder)
