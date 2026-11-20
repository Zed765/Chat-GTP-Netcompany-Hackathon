# Log inbox

Drop a proxy log (Squid `access.log` format, `*.log`) or a DNS query log (`*.dns`) here and
the gateway ingests it within a minute. A file is ingested once; its content is identified
by hash. The same files can be uploaded on the Inventory page or posted to
`POST /api/discovery/logs`.
