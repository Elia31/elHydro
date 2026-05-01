idf_component_register(
    SRCS "display_ui.c"
    INCLUDE_DIRS "."
    REQUIRES display_hal font5x7
    PRIV_INCLUDE_DIRS
        "../../main"
)