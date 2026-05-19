import http.client
import json
import time

# --------------------------------------------------------------- #
#           Config e Inicialização
# --------------------------------------------------------------- #

config = {
    "print": True,                      # default: False
    "rate_safety_factor": 0.85,         # default: 0.8
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
bitrate_teste = teste_bitrate(0)

if config["print"]: print(f"Bitrate do teste: {bitrate_teste} kbps\n")

# --------------------------------------------------------------- #



# --------------------------------------------------------------- #
#           Rate-Based ABR
# --------------------------------------------------------------- #

# margem de segurança pra escolha da bitrate
safety_factor:float = config["rate_safety_factor"]

# mapeamento das bitrates referentes às qualidades
qualities_rates:dict[int, str] = {}
for rep in manifesto["representations"]:
    qualities_rates[rep["bitrate_kbps"]] = rep["quality"]

if config["print"]: print(f"Bitrates das qualidades disponíveis: {qualities_rates}\n")

# escolhe a maior qualidade disponível cuja bitrate seja inferior à vazão da bitrate referência, com fator de segurança
def choose_quality(ref_rate:int)->tuple[str,int]:

    chosen_quality:str = ""
    chosen_rate:int = 0

    for rate, quality in qualities_rates.items():
        if (bitrate_teste * safety_factor >= rate):
            chosen_quality, chosen_rate = quality, rate

    return (chosen_quality, chosen_rate)

# faz a primeira escolha de qualidade com base na bitrate do teste
current_quality_rate = choose_quality(bitrate_teste)

if config["print"]: print(f"Primeira Qualidade | Bitrate escolhida: {current_quality_rate[0]} | {current_quality_rate[1]} kbps\n")

# --------------------------------------------------------------- #

conexao.close()