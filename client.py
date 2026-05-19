import http.client
import json

config = {
    "print": True,
}

# --------------------------------------------------------------- #
#           Requisição do Manifesto
# --------------------------------------------------------------- #

# inicia conexão (http://137.131.178.229:8080)
conexao = http.client.HTTPConnection("137.131.178.229", 8080)

# requisição GET
conexao.request("GET", "/manifest")
response = conexao.getresponse()
manifesto = json.loads(response.read())

conexao.close()
# --------------------------------------------------------------- #


if config["print"]:
    manifesto_pretty = json.dumps(manifesto, indent=3)
    print(manifesto_pretty)