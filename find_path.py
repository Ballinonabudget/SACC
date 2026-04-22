import json

def search_jordan(obj, path=""):
    if isinstance(obj, dict):
        if "Jordan" in str(obj.values()) and ("styleId" in obj or "style_code" in obj or "colorway" in obj or "retailPrice" in obj or "price" in obj):
            print(f"Found something at {path}")
            print(list(obj.keys()))
            return True
        for k, v in obj.items():
            if search_jordan(v, path + f"['{k}']"):
                return True
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            if search_jordan(item, path + f"[{i}]"):
                return True
    return False

with open('dump.json') as f:
    data = json.load(f)

search_jordan(data)
