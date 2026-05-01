idf_component_register(
    SRCS "display_hal.c"
    INCLUDE_DIRS "."
    REQUIRES epd_bw epd_bwr epd_color font5x7
    PRIV_INCLUDE_DIRS 
        "../../main"
)