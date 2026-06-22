import http.client
import json
import time
import csv
import matplotlib.pyplot as plt

config = {
    "print": True,
    "rate_safety_factor": 0.85,
    "address": "137.131.178.229",
    "port": 8080
}

endereco = config["address"]
porta = config["port"]

# inicia conexão
conexao = http.client.HTTPConnection(endereco, porta)

conexao.request("GET", "/manifest")
resposta = conexao.getresponse()
manifesto: dict[str] = json.loads(resposta.read())

if config["print"]:
    manifesto_pretty = json.dumps(manifesto, indent=3)
    print(f"\n{manifesto_pretty}\n")

with open("manifesto.json", "w", encoding="utf-8") as arquivo:
    json.dump(manifesto, arquivo, indent=3)

representacoes = manifesto["representations"]

def teste_bitrate(num_qualidade: int) -> int:

    qualidade = manifesto["representations"][num_qualidade]["quality"]
    n_bytes = manifesto["representations"][num_qualidade]["segment_bytes"]

    conexao.request("GET", f"/segment/{qualidade}")
    response = conexao.getresponse()

    tempo_download = time.time()
    response.read()
    tempo_download = time.time() - tempo_download

    return (8 * n_bytes / tempo_download) // 1000


bitrate_teste = teste_bitrate(0)

if config["print"]:
    print(f"Bitrate do teste: {bitrate_teste} kbps\n")

# Rate-Based ABR

safety_factor: float = config["rate_safety_factor"]

qualities_rates: dict[int, str] = {}
for rep in manifesto["representations"]:
    qualities_rates[rep["bitrate_kbps"]] = rep["quality"]

def escolher_qualidade(ref_rate: int) -> tuple[str, int]:

    qualidade_escolhida: str = list(qualities_rates.values())[0]
    rate_escolhido: int = list(qualities_rates.keys())[0]

    for rate, quality in qualities_rates.items():
        if (ref_rate * safety_factor >= rate):
            qualidade_escolhida, rate_escolhido = quality, rate

    return (qualidade_escolhida, rate_escolhido)

qualidade_atual = escolher_qualidade(bitrate_teste)

if config["print"]:
    print(
        f"Primeira Qualidade | Bitrate escolhida: "
        f"{qualidade_atual[0]} | {qualidade_atual[1]} kbps\n"
    )

# Estado inicial do ABR

vazao_media = bitrate_teste
historico = []
janela_media = 5

vazao_media_log = []
throughput_log = []
qualidade_log = []

SEGUNDOS_POR_SEGMENTO = 4.0
buffer = 8.0
rebuffer_time = 0.0
ultimo_tempo_baixar = None  # Para cálculo do Jitter

csv_file = open("metricas_tarefa1.csv", "w", newline="", encoding="utf-8")
writer = csv.writer(csv_file)

writer.writerow([
    "segmento",
    "timestamp",
    "download_time_s",
    "jitter_s",
    "qualidade",
    "bitrate_kbps",
    "throughput_kbps",
    "vazao_media_kbps",
    "buffer_s",
    "buffer_can_play",
    "rebuffer_total_s"
])

# Loop principal ABR
for segmento in range(20):

    quality, rate = escolher_qualidade(vazao_media)

    print(f"\nSegmento {segmento+1}")
    print(f"Qualidade escolhida: {quality} | {rate} kbps")

    # Avaliação do buffer antes do segmento chegar
    # Verifica se consegue manter o play contínuo naquele instante
    buffer_can_play = 1 if buffer > 2 else 0

    conexao.request("GET", f"/segment/{quality}")
    response = conexao.getresponse()

    inicio = time.time()
    dados = response.read()
    tempo_baixar = time.time() - inicio

    throughput = (8 * len(dados) / tempo_baixar) / 1000

    print(f"Throughput: {throughput:.2f} kbps")

    historico.append(throughput)

    if len(historico) > janela_media:
        historico.pop(0)

    vazao_media = sum(historico) / len(historico)

    print(f"Vazão média: {vazao_media:.2f} kbps")

    vazao_media_log.append(vazao_media)
    throughput_log.append(throughput)
    qualidade_log.append(rate)

    jitter = 0.0
    if ultimo_tempo_baixar is not None:
        jitter = abs(1000*(tempo_baixar - ultimo_tempo_baixar))
    ultimo_tempo_baixar = tempo_baixar
    print(f"Jitter: {jitter:.2f}ms")

    # Enquanto baixava o segmento, o player consumiu tempo do buffer
    if buffer >= tempo_baixar:
        buffer -= tempo_baixar
    else:
        # Tempo de download maior que o buffer
        rebuffer_time += (tempo_baixar - buffer)
        buffer = 0.0
        print("REBUFFERING")

    buffer += SEGUNDOS_POR_SEGMENTO
    print(f"Buffer atual: {buffer:.2f}s | Rebuffer acumulado: {rebuffer_time:.2f}s")

    timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")

    writer.writerow([
        segmento + 1,
        timestamp,
        round(tempo_baixar, 4),
        round(jitter, 4),
        quality,
        rate,
        round(throughput, 2),
        round(vazao_media, 2),
        round(buffer, 2),
        buffer_can_play,
        round(rebuffer_time, 2)
    ])

csv_file.close()
conexao.close()

'''
plt.figure(figsize=(12, 5))

plt.subplot(1, 2, 1)
plt.plot(throughput_log, label="Throughput")
plt.plot(vazao_media_log, label="Vazão Média")
plt.title("Vazão ao longo dos segmentos")
plt.xlabel("Segmento")
plt.ylabel("kbps")
plt.legend()
plt.grid(True)

plt.subplot(1, 2, 2)
plt.plot(qualidade_log, marker="o", color='orange')
plt.title("Qualidade Escolhida (Decisão ABR)")
plt.xlabel("Segmento")
plt.ylabel("Bitrate (kbps)")
plt.grid(True)

plt.tight_layout()
plt.show()'''