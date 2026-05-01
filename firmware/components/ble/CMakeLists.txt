idf_component_register(
    SRCS "ble_link.c"
    INCLUDE_DIRS "."
    REQUIRES nvs_flash bt esp_event
    PRIV_INCLUDE_DIRS 
        "../../main"
)