"""SCH5127 observations only; never write a hardware-monitor data register.

Reference: Microchip DS00002081A sections 24.20.1.3 and 25.2, and
figure 24-2. The caller must verify this H340's runtime base before use.
"""


def read_sensors(io, fan_input):
    if type(fan_input) is not int or fan_input not in (1, 2, 3):
        raise ValueError("Invalid configured fan input")
    index, data = 0x0870, 0x0871
    previous = io.read(index)

    def read_register(number):
        io.write(index, number)
        return io.read(data)

    try:
        if (read_register(0x3D), read_register(0x3E)) != (0x8E, 0x5C):
            raise RuntimeError("Unexpected SCH5127 hardware-monitor identity")
        low = 0x28 + 2 * (fan_input - 1)
        # The chip latches the paired high byte on low-byte access.
        count = read_register(low) | (read_register(low + 1) << 8)
        options = read_register(0x90 + fan_input - 1)
        raw_temperatures = [read_register(r) for r in (0x25, 0x26, 0x27)]
    finally:
        io.write(index, previous)
    if count in (0xFFFF, 0xFFFE):
        healthy = False
    elif count == 0:
        healthy = None
    else:
        healthy = True
    # RPM conversion is restricted to the verified default five-edge mode;
    # other programmed modes are not silently assigned an invented scale.
    rpm = 5400000 // count if healthy and options & 6 == 4 else None
    return {"fan_healthy": healthy, "fan_input": fan_input,
            "fan_tach_count": count, "fan_rpm": rpm,
            "sensor_temperatures_unlabelled": [v if v < 128 else v - 256
                                               for v in raw_temperatures]}
