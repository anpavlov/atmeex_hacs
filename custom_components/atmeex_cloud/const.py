DOMAIN = "atmeex_cloud"
CONF_ACCESS_TOKEN = "access_token"
CONF_REFRESH_TOKEN = "refresh_token"

PLATFORMS = [
    "binary_sensor",
    "climate",
    "fan",
    "number",
    "select",
    "sensor",
    "switch",
]

# Devices without the sensor send zero for these readings, real air never reads zero
ZERO_MEANS_MISSING = {"co2_ppm", "hum_room"}

# Only devices with a humidifier report room humidity; hum_stg comes from every device
HUMIDIFIER_READING = "hum_room"

SPEEDS = [
    "speed_1",
    "speed_2",
    "speed_3",
    "speed_4",
    "speed_5",
    "speed_6",
    "speed_7"
]