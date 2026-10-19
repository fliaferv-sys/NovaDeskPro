"""Explicit authorization scope; network labels never assign institutional fields."""
from dataclasses import dataclass
import ipaddress


@dataclass(frozen=True)
class AuthorizedNetwork:
    subnet: str
    site: str
    sector: str


NETWORKS = tuple(
    AuthorizedNetwork(f"10.{octet}.42.0/24", "VILLA_ELISA", sector)
    for octet, sector in (
        (2, "Almacenes"), (3, "Biodiesel"), (5, "Comercial"), (6, "DGE"), (7, "DSIMA"),
        (9, "Facturación"), (10, "GLP"), (11, "Informática / Enfermería"), (12, "Laboratorio"),
        (13, "Muelle"), (14, "Obras"), (15, "RRHH"), (17, "Portería Vieja"), (18, "WiFi"),
        (19, "EESS"), (20, "Ñu Guazú"), (21, "FAP"),
        (22, "PENDIENTE_CONFIRMAR"), (23, "PENDIENTE_CONFIRMAR"),
        (24, "PENDIENTE_CONFIRMAR"), (25, "PENDIENTE_CONFIRMAR"),
    )
) + tuple(
    AuthorizedNetwork(f"10.{octet}.32.0/24", "OFICINA_CENTRAL", floor)
    for octet, floor in ((8, "Piso 8"), (9, "Piso 9"), (10, "Piso 10"), (11, "Piso 11"),
                         (12, "Piso 12"), (14, "Piso 14"), (15, "Piso 15"), (16, "Piso 1"))
)
NETWORK_MAP = {entry.subnet: entry for entry in NETWORKS}
SITES = ("VILLA_ELISA", "OFICINA_CENTRAL")


def authorized_network(subnet):
    network = ipaddress.ip_network(subnet, strict=True)
    if network.version != 4 or network.prefixlen != 24 or str(network) not in NETWORK_MAP:
        raise ValueError("UNAUTHORIZED_SUBNET")
    return NETWORK_MAP[str(network)]


def select_networks(*, subnets=None, site=None, all_authorized=False):
    if sum((bool(subnets), bool(site), bool(all_authorized))) != 1:
        raise ValueError("Select exactly one authorization scope")
    if all_authorized:
        return list(NETWORKS)
    if site:
        if site not in SITES:
            raise ValueError("INVALID_SITE")
        return [entry for entry in NETWORKS if entry.site == site]
    return list(dict.fromkeys(authorized_network(subnet) for subnet in subnets))
