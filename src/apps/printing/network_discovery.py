"""Discovery restricted to the explicit authorized map; no ORM in HTTP threads."""
from concurrent.futures import ThreadPoolExecutor

from .discovery_adapters import identify_host
from .network_map import authorized_network
from .network_recovery import validate_scan_options


def discover_subnet(subnet, *, timeout=1, workers=8):
    entry = authorized_network(subnet)
    network, timeout = validate_scan_options(entry.subnet, timeout, workers)
    scan = dict(subnet=entry.subnet, site=entry.site, sector=entry.sector,
                status="COMPLETE", scanned_hosts=0, findings=[], error="")

    def probe(ip):
        try:
            return identify_host(ip, timeout=timeout), False
        except Exception:
            return None, True

    def collect(results):
        for finding, failed in results:
            scan["scanned_hosts"] += 1
            if failed:
                scan.update(status="INVALID", error="INCOMPLETE_SCAN")
            if finding:
                scan["findings"].append({**finding, "subnet": entry.subnet, "site": entry.site, "sector": entry.sector})

    ips = (str(host) for host in network.hosts())
    try:
        if workers == 1:
            collect(map(probe, ips))
        else:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                collect(executor.map(probe, ips))
    except Exception:
        scan.update(status="INVALID", error="INCOMPLETE_SCAN")
    if scan["scanned_hosts"] != 254:
        scan.update(status="INVALID", error="INCOMPLETE_SCAN")
    for finding in scan["findings"]:
        finding["scan_complete"] = scan["status"] == "COMPLETE"
    return scan


def discover_networks(subnets, *, timeout=1, workers=8):
    # Validate every network before the first HTTP request, and deduplicate scope.
    entries = list(dict.fromkeys(authorized_network(subnet) for subnet in subnets))
    for entry in entries:
        validate_scan_options(entry.subnet, timeout, workers)
    return [discover_subnet(entry.subnet, timeout=timeout, workers=workers) for entry in entries]
