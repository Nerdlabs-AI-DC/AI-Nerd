from prometheus_client import start_http_server, Counter, Gauge

start_http_server(8000)

messages_sent = Counter('messages_sent', 'Amount of messages sent by the bot')
users = Counter('users', 'Amount of users who talked to the bot')
servers = Gauge('servers', 'Amount of servers the bot is in')