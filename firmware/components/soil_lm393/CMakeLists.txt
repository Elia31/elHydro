idf_component_register(
    SRCS "lm393.c"
    INCLUDE_DIRS "."
    REQUIRES driver esp_adc
)