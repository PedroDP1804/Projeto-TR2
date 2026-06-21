import http.client
from http.client import HTTPException
import json
import time
import csv
import matplotlib.pyplot as mplot
from matplotlib.ticker import MaxNLocator


# --------------------------------------------------------------- #
#           Config
# --------------------------------------------------------------- #

config = {
    "print_logs": True,                                 # Logs da execução
    "fator_de_seguranca": 0.85,                         # Fator de segurança pra escolha da qualidade
    "janela_da_media": 3,                               # Número de bitrates anteriores consideradas na média
    "num_segmentos": 20,                                # Número de segmentos a serem baixados na execução do programa
    "min_buffer_play": 3,                               # Mínimo de segundos em buffer para dar play
    "min_buffer_subir": 10,                             # Valor do buffer em segundos para subir a qualidade
    "url_inicial": "137.131.178.229:8080",              # URL da conexão inicial
    "alpha_ewma": 0.125                                 # Constante de suavização do Jitter
}

def print_log(msg:str):
    if config["print_logs"]:
        print(msg)

# <-------------------------------------------------------------> #


# --------------------------------------------------------------- #
#           GET do Manifesto
# --------------------------------------------------------------- #

# inicia conexão
conexao = http.client.HTTPConnection(config["url_inicial"])

conexao.request("GET", "/manifest")
resposta = conexao.getresponse()
manifesto: dict[str] = json.loads(resposta.read())

print_log(json.dumps(manifesto, indent=3))

with open("manifesto.json", "w", encoding="utf-8") as arquivo:
    json.dump(manifesto, arquivo, indent=3)

representacoes = sorted(manifesto["representations"], key=lambda r: r["bitrate_kbps"])

# <-------------------------------------------------------------> #


# --------------------------------------------------------------- #
#               Funções
# --------------------------------------------------------------- #

def escolher_qualidade(ref_rate: int, buffer: float, tendencia: float, jitter_suavizado: float) -> tuple[str, int]:

    global qualidades, bitrates

    qualidade_escolhida = qualidades[0]
    rate_escolhido = bitrates[0]
    fator: float = config["fator_de_seguranca"]

    fator_buffer = max(1, (buffer - config["min_buffer_subir"])) # minimo 1
    print_log(f"\tMultiplicador de buffer: x{fator_buffer:.4f}")

    fator = fator * fator_buffer

    # Penalidade por Tendência (Regressão Linear)
    if tendencia < -100.0:
        print_log("\tTendência de queda brusca. Penalidade de 20%.")
        fator *= 0.80
    elif tendencia < -10.0:
        print_log("\tTendência de queda. Penalidade de 10%.")
        fator *= 0.90
        
    # Penalidade por Jitter (EWMA)
    if jitter_suavizado > 100.0:
        print_log(f"\tJitter alto ({jitter_suavizado:.2f}ms). Penalidade de 25%.")
        fator *= 0.75

    for rate, quality in qualities_rates.items():
        if (ref_rate * fator >= rate):
            qualidade_escolhida, rate_escolhido = quality, rate

    return (qualidade_escolhida, rate_escolhido)


def calcular_tendencia(vazoes: list) -> float:
    n = len(vazoes)
    if n < 2:
        return 0.0
    
    x = list(range(1, n + 1))
    y = vazoes
    
    sum_x = sum(x)
    sum_y = sum(y)
    sum_xy = sum(i * j for i, j in zip(x, y))
    sum_x_quad = sum(i**2 for i in x)
    
    denominador = (n * sum_x_quad) - (sum_x ** 2)
    if denominador == 0:
        return 0.0
        
    return ((n * sum_xy) - (sum_x * sum_y)) / denominador

# <-------------------------------------------------------------> #


# --------------------------------------------------------------- #
#           Inicialização
# --------------------------------------------------------------- #

# Mapeamento das qualidades e bitrates
qualities_rates: dict[int, str] = {}
for rep in representacoes:
    qualities_rates[rep["bitrate_kbps"]] = rep["quality"]

bitrates = list(qualities_rates.keys())
qualidades = list(qualities_rates.values())

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
def teste_bitrate(num_qualidade: int) -> int:

    qualidade = representacoes[num_qualidade]["quality"]
    n_bytes = representacoes[num_qualidade]["segment_bytes"]

    conexao.request("GET", f"/segment/{qualidade}")
    response = conexao.getresponse()

    tempo_download = time.time()
    response.read()
    tempo_download = time.time() - tempo_download

    return (8 * n_bytes / tempo_download) // 1000

bitrate_teste = teste_bitrate(0)

print_log(f"Bitrate do teste: {bitrate_teste} kbps\n")

# Parametros
segundos_por_segmento:float = manifesto["segment_duration_s"]
tamanho_janela_media = config["janela_da_media"]

qualidade_atual = escolher_qualidade(bitrate_teste, 0.0, 0.0, 0.0)
vazao_media = bitrate_teste

print_log(f"Primeira Qualidade | Bitrate escolhida: {qualidade_atual[0]} | {qualidade_atual[1]} kbps\n\n")

# Logs
logs_csv = {
    "segment": [],
    "timestamp": [],
    "server_id": [],
    "quality": [],
    "bitrate_kbps": [],
    "vazao_kbps": [],
    "download_time_s": [],
    "jitter_network_ms": [],
    "jitter_ewma_ms": [],
    "buffer_level_s": [],
    "buffer_can_play": [],
    "rebuffer_event": [],
    "stall_duration_s": [],
    "failover_total": [],
}
logs_vazao_media = [] # p/ graficos

# Estado
index_servidor = 0                  # Index do servidor conectado atualmente (da lista de servidores)
ultimas_vazoes = []                 # vazoes instantaneas recentes p/ calcular media
buffer = 0.0                        # segundos em buffer
rebuffer_acumulado = 0.0            # tempo acumulado de rebuffer
failover_total = 0                  # número acumulado de failovers
rebuffer_no_ultimo = False          # se teve rebuffer no ultimo segmento
ultimo_tempo_download = None        # Para cálculo do Jitter
ultimo_tempo_atual = time.time()    # medição do tempo real para medir o tempo decorrido
jitter_ewma = 0.0                   # Estado inicial do Jitter EWMA
tendencia_rede = 0.0                # Estado inicial da inclinação de tendência

# <-------------------------------------------------------------> #


# --------------------------------------------------------------- #
#           Loop Principal do ABR
# --------------------------------------------------------------- #

SIMULAR_FALHA = True
SEGMENTO_FALHA = 10
falha_ja_ocorreu = False
tempo_failover_ms = 0.0

def baixar_segmento(qualidade):

    global conexao, segmento, index_servidor
    global falha_ja_ocorreu

    # SIMULAÇÃO DE QUEDA DO SERVIDOR A
    if (
        SIMULAR_FALHA
        and segmento == SEGMENTO_FALHA
        and index_servidor == 0
        and not falha_ja_ocorreu
    ):
        falha_ja_ocorreu = True
        raise OSError("Servidor A indisponível (SIMULAÇÃO)")

    conexao.request("GET", f"/segment/{qualidade}")
    response = conexao.getresponse()

    inicio = time.perf_counter()
    
    # Leitura segmentada (chunks) para aferição de Jitter intra-segmento
    chunk_size = 8192
    dados = bytearray()
    tempos_chunks = []
    
    ultimo_tempo = time.perf_counter()
    while True:
        chunk = response.read(chunk_size)
        if not chunk:
            break
        agora = time.perf_counter()
        tempos_chunks.append(agora - ultimo_tempo)
        ultimo_tempo = agora
        dados.extend(chunk)
        
    tempo_download = time.perf_counter() - inicio

    # Cálculo de Jitter (Média da variação de atraso entre chunks)
    jitter_ms = 0.0
    if len(tempos_chunks) > 1:
        diferencas = [abs(tempos_chunks[i] - tempos_chunks[i-1]) for i in range(1, len(tempos_chunks))]
        jitter_ms = (sum(diferencas) / len(diferencas)) * 1000.0

    return bytes(dados), tempo_download, jitter_ms

def calcular_media(vazao_atual:float)->float:
    global logs_csv, tamanho_janela_media, ultimas_vazoes

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

            qualidade, bitrate_escolhida = escolher_qualidade(vazao_media, buffer, tendencia_rede, jitter_ewma)
            print_log(f"\tQualidade escolhida: {qualidade} | {bitrate_escolhida} kbps")

            dados, tempo_download, jitter_rede = baixar_segmento(qualidade)

            # Vazão Atual
            vazao_atual = (8 * len(dados) / tempo_download) / 1000

            print_log(f"\tVazão Atual: {vazao_atual:.2f} kbps")

            # Cálculo da média
            vazao_media = calcular_media(vazao_atual)
            logs_vazao_media.append(vazao_media)

            print_log(f"\tVazão média: {vazao_media:.2f} kbps")
            print_log(f"\tJitter da Rede: {jitter_rede:.2f} ms")

            # Processamento Estatístico
            if segmento == 1:
                jitter_ewma = jitter_rede
            else:
                alpha = config["alpha_ewma"]
                jitter_ewma = (alpha * jitter_rede) + ((1.0 - alpha) * jitter_ewma)
            
            tendencia_rede = calcular_tendencia(ultimas_vazoes)

            # Jitter (ms) antigo mantido para retrocompatibilidade do log
            jitter = 0.0
            if ultimo_tempo_download is not None:
                jitter = 1000 * abs(tempo_download - ultimo_tempo_download)
            ultimo_tempo_download = tempo_download
            
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

            timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")
            logs_csv["segment"].append(segmento)
            logs_csv["timestamp"].append(timestamp)
            logs_csv["server_id"].append(servidores[index_servidor]["id"])
            logs_csv["quality"].append(qualidade)
            logs_csv["bitrate_kbps"].append(bitrate_escolhida)
            logs_csv["vazao_kbps"].append(vazao_atual)
            logs_csv["download_time_s"].append(round(tempo_download, 4))
            logs_csv["jitter_network_ms"].append(round(jitter_rede, 4))
            logs_csv["jitter_ewma_ms"].append(round(jitter_ewma, 4))
            logs_csv["buffer_level_s"].append(buffer)
            logs_csv["buffer_can_play"].append(int(buffer_can_play))
            logs_csv["rebuffer_event"].append(int(rebuffer_no_ultimo))
            logs_csv["stall_duration_s"].append(tempo_rebuffer)
            logs_csv["failover_total"].append(failover_total)

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
conexao.close()


# --------------------------------------------------------------- #
#           Métricas CSV
# --------------------------------------------------------------- #

csv_file = open("metricas_tarefa3.csv", "w", newline="", encoding="utf-8")
writer = csv.writer(csv_file)

# headers
writer.writerow(list(logs_csv.keys()))

for i in segmentos:
    linha = []
    for coluna in logs_csv.values():
        linha.append(coluna[i-1])
    writer.writerow(linha)

csv_file.close()


# --------------------------------------------------------------- #
#           Gráficos
# --------------------------------------------------------------- #

figura, graficos = mplot.subplots(nrows=1, ncols=3, figsize=(12, 8))

# Gráfico 1: Vazão instantânea
graficos[0].set_title("Vazão Instantânea (kbps)")
graficos[0].set_xlabel("Segmento")
graficos[0].plot(segmentos, logs_csv["vazao_kbps"])
graficos[0].xaxis.set_major_locator(MaxNLocator(integer=True))

lim = (
    max(0, min(logs_csv["vazao_kbps"]) - 500),
    max(logs_csv["vazao_kbps"]) + 500
)
graficos[0].set_ylim(lim)

# Gráfico 2: Vazão Média e Qualidade
cor_vazao = "tab:blue"

graficos[1].set_title("Vazão Média (kbps) e Qualidade")
graficos[1].set_xlabel("Segmento")

linha1 = graficos[1].plot(
    segmentos,
    logs_vazao_media,
    color=cor_vazao,
    label="Vazão Média"
)

graficos[1].xaxis.set_major_locator(MaxNLocator(integer=True))

cor_qualidade = "tab:orange"
eixo_qualidade = graficos[1].twinx()

linha2 = eixo_qualidade.plot(
    segmentos,
    logs_csv["bitrate_kbps"],
    color=cor_qualidade,
    label="Qualidade"
)

eixo_qualidade.set_yticks(bitrates)
eixo_qualidade.set_yticklabels(qualidades)

lim = (
    max(0, min(logs_csv["bitrate_kbps"]) - 500),
    max(logs_csv["bitrate_kbps"]) + 500
)

graficos[1].set_ylim(lim)
eixo_qualidade.set_ylim(lim)

linhas = linha1 + linha2
labels = [l.get_label() for l in linhas]
graficos[1].legend(linhas, labels, loc="upper left")

# Gráfico 3: Nível do buffer
graficos[2].set_title("Nível do Buffer (s)")
graficos[2].set_xlabel("Segmento")
graficos[2].plot(segmentos, logs_csv["buffer_level_s"])
graficos[2].xaxis.set_major_locator(MaxNLocator(integer=True))

mplot.tight_layout()
mplot.show()