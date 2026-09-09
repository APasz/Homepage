"""Stable paths for the hub's public and configuration routes."""

from enum import StrEnum

from apasz_hub.config_security import (
    CONFIG_LOGIN_PATH,
    CONFIG_LOGOUT_PATH,
    CONFIG_PATH,
)


class SiteRoute(StrEnum):
    """Named HTTP paths used by pages and route handlers."""

    HOME = "/"
    CONFIG = CONFIG_PATH
    CONFIG_LOGIN = CONFIG_LOGIN_PATH
    CONFIG_LOGOUT = CONFIG_LOGOUT_PATH
    CONFIG_COLOURS_SAVE = f"{CONFIG_PATH}/colours"
    CONFIG_LINK_CARDS_DRAFT = f"{CONFIG_PATH}/link-cards/draft"
    CONFIG_LINK_CARDS_ADD = f"{CONFIG_PATH}/link-cards/add"
    CONFIG_LINK_CARDS_DELETE = f"{CONFIG_PATH}/link-cards/delete"
    CONFIG_LINK_CARDS_SAVE = f"{CONFIG_PATH}/link-cards"
