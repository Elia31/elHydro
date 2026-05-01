idf_component_register(
    SRCS "epd_color_driver.c"
    INCLUDE_DIRS "."
    REQUIRES driver esp_timer freertos heap log
)