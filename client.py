import http.client
import json
import time

# --------------------------------------------------------------- #
#           Config e Inicialização
# --------------------------------------------------------------- #

config = {
    "print": True,                      # default: False
    "multiple_bitrate_tests": True,     # default: False
    "address": "137.131.178.229",       # default: "137.131.178.229"
    "port": 8080                        # default: "8080"
}
address = config["address"]
port = config["port"] # temporario; TO-DO: decidir a porta verificando se o servidor tá no ar

# inicia conexão
conexao = http.client.HTTPConnection(address, port)

# --------------------------------------------------------------- #



# --------------------------------------------------------------- #
#           Requisição do Manifesto
# --------------------------------------------------------------- #

# requisição GET
conexao.request("GET", "/manifest")
response = conexao.getresponse()
manifesto:dict[str] = json.loads(response.read())


if config["print"]:
    manifesto_pretty = json.dumps(manifesto, indent=3)
    print(f"\n{manifesto_pretty}\n")

# --------------------------------------------------------------- #



# --------------------------------------------------------------- #
#           Medição da Bitrate
# --------------------------------------------------------------- #

def teste_bitrate(num_qualidade:int)->int:

    # qualidade do segmento teste
    qualidade = manifesto["representations"][num_qualidade]["quality"]
    n_bytes = manifesto["representations"][num_qualidade]["segment_bytes"]

    # requisição segmento teste
    conexao.request("GET", f"/segment/{qualidade}")
    response = conexao.getresponse()

    # medição do tempo de download
    tempo_download = time.time()
    response.read()
    tempo_download = time.time() - tempo_download

    # bitrate em kbps
    return (8 * n_bytes / tempo_download) // 1000

# testa na primeira qualidade disponível
bitrate_kbps = teste_bitrate(0)

if config["print"]: print(f"Bitrate: {bitrate_kbps} kbps\n")

# --------------------------------------------------------------- #




conexao.close()