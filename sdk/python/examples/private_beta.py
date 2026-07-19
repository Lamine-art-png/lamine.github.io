from agroai_platform import AgroAIPlatformClient


client = AgroAIPlatformClient()
print(client.me())
print(client.providers())
