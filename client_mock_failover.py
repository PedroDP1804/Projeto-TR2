import http.client
from http.client import HTTPException
import json
import time
import csv
import matplotlib.pyplot as mplot
from matplotlib.ticker import MaxNLocator


# --------------------------------------------------------------- #
#           Config e Inicialização
# --------------------------------------------------------------- #

config = {
    "print_logs": True,                           # Logs da execução
    "fator_de_seguranca": 0.85,                         # Fator de segurança pra escolha da qualidade
    "janela_da_media": 3,                               # Número de bitrates anteriores consideradas na média
    "num_segmentos": 20,                                # Número de segmentos a serem baixados na execução do programa
    "min_buffer_play": 3,                               # Mínimo de segundos em buffer para dar play
    "url_inicial": "137.131.178.229:8080",              # URL da conexão inicial
}

# inicia conexão
conexao = http.client.HTTPConnection(config["url_inicial"])

def print_log(msg:str):
    if config["print_logs"]:
        print(msg)

# <-------------------------------------------------------------> #


# --------------------------------------------------------------- #
#           GET do Manifesto
# --------------------------------------------------------------- #

conexao.request("GET", "/manifest")
resposta = conexao.getresponse()
manifesto: dict[str] = json.loads(resposta.read())

print_log(json.dumps(manifesto, indent=3))

with open("manifesto.json", "w", encoding="utf-8") as arquivo:
    json.dump(manifesto, arquivo, indent=3)

representacoes = manifesto["representations"]

# <-------------------------------------------------------------> #


# --------------------------------------------------------------- #
#               Funções
# --------------------------------------------------------------- #

# testa a bitrate na qualidade num_qualidade (na ordem do manifesto) e retorna a bitrate:int em kbps
def teste_bitrate(num_qualidade: int) -> int:

    qualidade = representacoes[num_qualidade]["quality"]
    n_bytes = representacoes[num_qualidade]["segment_bytes"]

    conexao.request("GET", f"/segment/{qualidade}")
    response = conexao.getresponse()

    tempo_download = time.time()
    response.read()
    tempo_download = time.time() - tempo_download

    return (8 * n_bytes / tempo_download) // 1000

def escolher_qualidade(ref_rate: int) -> tuple[str, int]:

    qualidade_escolhida: str = list(qualities_rates.values())[0]
    rate_escolhido: int = list(qualities_rates.keys())[0]
    fator_seguranca: float = config["fator_de_seguranca"]

    for rate, quality in qualities_rates.items():
        if (ref_rate * fator_seguranca >= rate):
            qualidade_escolhida, rate_escolhido = quality, rate

    return (qualidade_escolhida, rate_escolhido)

# <-------------------------------------------------------------> #


# --------------------------------------------------------------- #
#           Inicialização
# --------------------------------------------------------------- #

# Setup do CSV
csv_file = open("abr_log.csv", "w", newline="", encoding="utf-8")
writer = csv.writer(csv_file)

writer.writerow([
    "segment",
    "timestamp",
    "server_id",
    "quality",
    "bitrate_kbps",
    "vazao_kbps",
    "download_time_s",
    "jitter_network_ms",
    "jitter_ewma_ms",
    "buffer_level_s",
    "buffer_can_play",
    "rebuffer_event",
    "stall_duration_s",
    "failover_total",
])

# Mapeamento das qualidades e bitrates
qualities_rates: dict[int, str] = {}
for rep in representacoes:
    qualities_rates[rep["bitrate_kbps"]] = rep["quality"]

# Mapeamento dos servidores para failover
servidores = [s for s in sorted(manifesto["servers"], key=lambda server: server["priority"])]
for servidor in servidores:
    servidor["url"] = servidor["url"].split("://")[1] # Tirar 'https://'
    servidor.pop("bandwidth_kbps")
    servidor.pop("jitter_ms")

print_log(f"Servidores disponíveis: {servidores}")

# <-------------------------------------------------------------> #


# --------------------------------------------------------------- #
#           Estado inicial do ABR
# --------------------------------------------------------------- #

# Teste inicial de bitrate
bitrate_teste = teste_bitrate(0)
print_log(f"Bitrate do teste: {bitrate_teste} kbps\n")

# Parametros
segundos_por_segmento:float = manifesto["segment_duration_s"]
tamanho_janela_media = config["janela_da_media"]

qualidade_atual = escolher_qualidade(bitrate_teste)
vazao_media = bitrate_teste

print_log(f"Primeira Qualidade | Bitrate escolhida: {qualidade_atual[0]} | {qualidade_atual[1]} kbps\n\n")

# Logs
logs = {
    "vazao_atual": [],
    "vazao_media": [],
    "buffer": [],
    "bitrate_escolhida": [],
}

# Estado
index_servidor = 0                  # Index do servidor conectado atualmente (da lista de servidores)
ultimas_vazoes = []                 # vazoes instantaneas recentes p/ calcular media
buffer = 0.0                        # segundos em buffer
rebuffer_acumulado = 0.0            # tempo acumulado de rebuffer
failover_total = 0                  # número acumulado de failovers
rebuffer_no_ultimo = False          # se teve rebuffer no ultimo segmento
ultimo_tempo_download = None        # Para cálculo do Jitter
ultimo_tempo_atual = time.time()    # medição do tempo real  para medir o tempo decorrido desde o último segmento

# <-------------------------------------------------------------> #


# --------------------------------------------------------------- #
#           Loop Principal do ABR
# --------------------------------------------------------------- #
mock_failover = False
def baixar_segmento(qualidade):
    global conexao

    # Requisição
    conexao.request("GET", f"/segment/{qualidade}")

    # MOCK failover
    global mock_failover
    if mock_failover:
        conexao.sock.close()

    response = conexao.getresponse()

    # Download e medição do tempo de download
    tempo_download = time.time()
    dados = response.read()
    tempo_download = time.time() - tempo_download

    return (dados, tempo_download)

def calcular_media(vazao_atual:float)->float:
    global logs, tamanho_janela_media, ultimas_vazoes

    ultimas_vazoes.append(vazao_atual)
    if len(ultimas_vazoes) > tamanho_janela_media:
        ultimas_vazoes.pop(0)

    return sum(ultimas_vazoes) / len(ultimas_vazoes)



segmentos = range(1, config["num_segmentos"]+1)
n_servidores = len(servidores)
for segmento in segmentos:

    print_log(f">> Segmento {segmento}")


    # Mecanismo de Failover
    for tentativa in range(n_servidores):

        # checar saúde do servidor da tentativa
        conexao_health = http.client.HTTPConnection(servidores[tentativa]["url"])
        conexao_health.request("GET", "/health")
        response = conexao_health.getresponse()
        health = json.loads(response.read())
        conexao_health.close()

        # Mock Failover curto
        if segmento == 4 and tentativa == 0:
            mock_failover = True

        # MOCK Failover longo
        elif segmento == 7 and tentativa == 0:
            mock_failover = True
            print(f"   MOCK: Servidor de prioridade {tentativa+1} caiu por um bom tempo...")
        elif segmento > 7 and segmento <= 13 and tentativa == 0:
            health["status"] = "naum"

        else:
            mock_failover = False

        if health["status"] != "ok":
            print(f"\tServidor de prioridade {tentativa+1} inacessível.")
            continue

        # Se o servidor da tentativa estiver saudavel e for mais prioritario que o atual, reestabelece conexao com o prioritario
        elif index_servidor > tentativa:
            conexao.close()
            conexao = http.client.HTTPConnection(servidores[tentativa]["url"])
            index_servidor = tentativa
            print_log(f"   Conexão com servidor de maior prioridade (prioridade {tentativa}) reestabelecida.")


        temp = servidores[index_servidor]["url"]
        print_log(f"   Tentativa {tentativa+1} no servidor {temp}")

        try:

            qualidade, bitrate_escolhida = escolher_qualidade(vazao_media)
            print_log(f"\tQualidade escolhida: {qualidade} | {bitrate_escolhida} kbps")

            dados, tempo_download = baixar_segmento(qualidade)

            # Vazão Atual
            vazao_atual = (8 * len(dados) / tempo_download) / 1000

            print_log(f"\tVazão Atual: {vazao_atual:.2f} kbps")

            # Cálculo da média
            vazao_media = calcular_media(vazao_atual)

            print_log(f"\tVazão média: {vazao_media:.2f} kbps")

            # Jitter (ms)
            jitter = 0.0
            if ultimo_tempo_download is not None:
                jitter = 1000 * abs(tempo_download - ultimo_tempo_download)
            ultimo_tempo_download = tempo_download

            print_log(f"\tJitter: {jitter:.2f}ms")
            
            # Tempo decorrido desde o último segmento
            tempo_decorrido = time.time() - ultimo_tempo_atual
            ultimo_tempo_atual = time.time()

            tempo_rebuffer = 0.0                            # Tempo de rebuffer nesse segmento
            buffer_can_play = buffer >= tempo_decorrido     # Verifica se consegue manter o play contínuo naquele instante

            # Verificar continuidade do player
            if rebuffer_no_ultimo:
                # Despausar
                if buffer >= config["min_buffer_play"]:
                    buffer -= tempo_decorrido
                    rebuffer_no_ultimo = False
                    pass

                # Continua em rebuffer
                else:
                    tempo_rebuffer = tempo_decorrido
                    rebuffer_acumulado += tempo_rebuffer
                    rebuffer_no_ultimo = True
                    print("\t<!> STILL REBUFFERING")
                    pass
            else:
                # Play continuo
                if buffer_can_play:
                    buffer -= tempo_decorrido
                    rebuffer_no_ultimo = False

                # Travou agora
                else:
                    tempo_rebuffer = tempo_decorrido - buffer
                    rebuffer_acumulado += tempo_rebuffer
                    buffer = 0.0  # buffer esgotado
                    rebuffer_no_ultimo = True
                    print("\t<!> REBUFFERING")

            buffer += segundos_por_segmento

            print_log(f"\tBuffer atual: {buffer:.2f}s | Rebuffer acumulado: {rebuffer_acumulado:.2f}s")


            print_log(f"   Tentativa bem sucedida!\n")
            id_servidor = servidores[tentativa]["id"]

            logs["bitrate_escolhida"].append(bitrate_escolhida)
            logs["vazao_atual"].append(vazao_atual)
            logs["vazao_media"].append(vazao_media)
            logs["buffer"].append(buffer)

            # Registrar no CSV
            # TO-DO: implementar as métricas faltantes
            timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")
            writer.writerow([
                segmento,                           # "segment"
                timestamp,                          # "timestamp"
                servidores[index_servidor]["id"],   # "server_id"
                qualidade,                          # "quality"
                bitrate_escolhida,                  # "bitrate_kbps"
                vazao_atual,                        # "vazao_kbps"
                round(tempo_download, 4),           # "download_time_s"
                "null",                             # "jitter_network_ms" #TO-DO
                "null",                             # "jitter_ewma_ms" #TO-DO
                buffer,                             # "buffer_level_s"
                int(buffer_can_play),               # "buffer_can_play"
                int(rebuffer_no_ultimo),            # "rebuffer_event"
                tempo_rebuffer,                     # "stall_duration_s"
                failover_total,                     # "failover_total"
            ])

            break

        except (HTTPException, OSError) as e:

            # Registrar Failover
            failover_total += 1

            # Troca de servidor
            if tentativa < n_servidores - 1:
                print("   Tentativa falhou. Tentando próximo servidor...\n")
                conexao.close()
                conexao = http.client.HTTPConnection(servidores[tentativa+1]["url"])
                index_servidor = tentativa+1

            else:
                print("<!> Sem servidores disponíveis. Encerrando...\n\n")
                raise RuntimeError


# <-------------------------------------------------------------> #

csv_file.close()
conexao.close()


# --------------------------------------------------------------- #
#           Gráficos
# --------------------------------------------------------------- #

figura, graficos = mplot.subplots(nrows=2, ncols=2, figsize=(12, 5))

# Gráfico 1: Vazão instantânea
graficos[0, 0].set_title("Vazão Instantânea (kbps)")
graficos[0, 0].set_xlabel("Segmento")
# graficos[0, 0].set_ylabel("kbps")
graficos[0, 0].plot(segmentos, logs["vazao_atual"])
graficos[0, 0].xaxis.set_major_locator(MaxNLocator(integer=True))
graficos[0, 0].set_ylim(0, 3000)


# Gráfico 2: Vazão Média e Qualidade

# vazão média
cor_vazao = "tab:blue"
graficos[0, 1].set_title("Vazão Média (kbps) e Qualidade")
graficos[0, 1].set_xlabel("Segmento")
# graficos[0, 1].set_ylabel("kbps")
linha1 = graficos[0, 1].plot(segmentos, logs["vazao_media"], color=cor_vazao, label="Vazão Média")
graficos[0, 1].xaxis.set_major_locator(MaxNLocator(integer=True))

# qualidade
cor_qualidade = "tab:orange"
eixo_qualidade = graficos[0, 1].twinx()
# eixo_qualidade.set_ylabel("Qualidade")
linha2 = eixo_qualidade.plot(segmentos, logs["bitrate_escolhida"], color=cor_qualidade, label="Qualidade")
bitrates = list(qualities_rates.keys())
qualidades = list(qualities_rates.values())
eixo_qualidade.set_yticks(bitrates)
eixo_qualidade.set_yticklabels(qualidades)

# junção
graficos[0, 1].set_ylim(0, 3000)
eixo_qualidade.set_ylim(0, 3000)
linhas = linha1 + linha2
labels = [l.get_label() for l in linhas]
graficos[0, 1].legend(linhas, labels, loc='upper left')

# Gráfico 3: Nível do buffer
graficos[1, 0].set_title("Nível do Buffer (s)")
graficos[1, 0].set_xlabel("Segmento")
graficos[1, 0].plot(segmentos, logs["buffer"])
graficos[1, 0].xaxis.set_major_locator(MaxNLocator(integer=True))

#TO-DO
# Gráfico 4: ...

mplot.tight_layout()
mplot.show()

# --------------------------------------------------------------- #