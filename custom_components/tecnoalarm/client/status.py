"""Provisional panel status decoders, independent of transport and Home Assistant."""

import struct

# Opcode, response size, program offset, program count.
LAYOUTS = {
    **dict.fromkeys((25, 29, 30, 31, 32, 33, 34, 38, 39, 40, 41), (0x090D, 12, 4, 8)),
    13: (0x090D, 34, 2, 32),
    **dict.fromkeys((24, 35, 36, 44, 47, 48), (0x090D, 36, 4, 32)),
    **dict.fromkeys((45, 46), (0x090D, 20, 4, 16)),
    **dict.fromkeys((42, 43), (0x090D, 12, 4, 6)),
    **dict.fromkeys((49, 50), (0x0924, 64, 32, 8)),
    **dict.fromkeys((57, 58), (0x0924, 64, 32, 16)),
}
MODELS = {
    13: "TP256", 24: "TP512C", 25: "TP96V", 29: "TP828P", 30: "TP828G",
    31: "TP828PE", 32: "TP828GE", 33: "TP888", 34: "TP888E", 35: "TP440",
    36: "TP440E", 38: "TP42", 39: "TP42E", 40: "TP828BS", 41: "TP28PBS",
    42: "EV424", 43: "EV424E", 44: "TP440BS", 45: "TP888P", 46: "TP888PE",
    47: "TP312", 48: "TP312E", 49: "EV50", 50: "EV50E", 57: "EV150", 58: "EV150E",
}
LONG_NAMES = {35, 36, 44, 42, 43, 49, 50, 57, 58, 38, 39, 47, 48, 45, 46}
STATES = {
    0: "idle", 1: "pre_exit", 2: "exit", 3: "armed",
    4: "partial_exit", 5: "partial", 6: "partial_end",
}


def require_length(raw, size):
    if len(raw) != size:
        raise ValueError("Invalid status record length")


def decode_identity(raw):
    require_length(raw, 16)
    if raw[0] not in LAYOUTS:
        raise ValueError(f"Unsupported panel model ID: {raw[0]}")
    return {"model_id": raw[0], "model": MODELS[raw[0]], "firmware_nationality": raw[1],
            "raw_identity": raw.hex()}


def permission_size(model):
    return 12 if model in (35, 36, 47, 48) else 8


def description_size(model):
    return 32 if model in LONG_NAMES else 24


def authorized_indices(model, permissions):
    require_length(permissions, permission_size(model))
    mask = struct.unpack_from("<I", permissions)[0]
    return [index for index in range(LAYOUTS[model][3]) if mask & (1 << index)]


def decode_program(index, description, raw, nationality=0):
    # Greek firmware uses a different character encoding for program names.
    name = description[:16].split(b"\0", 1)[0].decode(
        "iso8859-7" if nationality == 5 else "utf-8", errors="replace")
    return {"index": index, "number": index + 1, "name": name or f"P{index + 1}",
            "state": STATES.get(raw & 15, "unknown"), "raw_status": raw,
            "raw_status_hex": f"{raw:02x}"}


def decode_status(identity_raw, permissions, groups, panel_status, descriptions,
                  *, source="live"):
    identity = decode_identity(identity_raw)
    model = identity["model_id"]
    _, size, offset, _ = LAYOUTS[model]
    require_length(groups, size)
    require_length(panel_status, 16)
    programs = []
    for index in authorized_indices(model, permissions):
        require_length(descriptions[index], description_size(model))
        programs.append(decode_program(index, descriptions[index], groups[offset + index],
                                       identity["firmware_nationality"]))
    return {"source": source, "provisional": True, "panel": {
        **identity, "alarm": bool(panel_status[9] & 0x20),
        "fault": bool(panel_status[8] & 2), "raw_status": panel_status.hex(),
    }, "programs": programs}
