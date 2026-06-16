import pandas as pd
import matplotlib.pyplot as plt

import subprocess

# O código primeiro executa as duas políticas para gerar os dois csv, então pode demorar um pouco
# Também pode ser necessário fechar os gráficos referentes às políticas para continuar quando aparecerem
print("Rodando baseline...")
subprocess.run(["python", "cliente_tarefa1.py"])

print("Rodando política 2...")
subprocess.run(["python", "cliente_tarefa2.py"])

print("Fim")

pol1 = pd.read_csv("abr_log.csv")
pol2 = pd.read_csv("metricas.csv")

n = min(len(pol1), len(pol2))
pol1 = pol1.iloc[:n]
pol2 = pol2.iloc[:n]

seg = range(1, n + 1)

# =================================================
# 1. VAZÃO
# =================================================
plt.figure(figsize=(10,5))

plt.plot(seg, pol1["throughput_kbps"], label="Baseline", alpha=0.7)
plt.plot(seg, pol2["vazao_kbps"], label="Política 2", alpha=0.7)

plt.title("Comparação de Vazão Instantânea")
plt.xlabel("Segmento")
plt.ylabel("kbps")
plt.legend()
plt.grid()
plt.xticks(range(2, n + 1, 2))
plt.show()


# =================================================
# 2. QUALIDADE
# =================================================
pol1 = pd.read_csv("abr_log.csv")
pol2 = pd.read_csv("metricas.csv")

n = min(len(pol1), len(pol2))
pol1 = pol1.iloc[:n]
pol2 = pol2.iloc[:n]

seg = range(1, n + 1)

bitrates = [200, 400, 700, 1500, 3000]
labels = ["240p", "360p", "480p", "720p", "1080p"]

plt.figure(figsize=(10,5))

plt.plot(seg, pol1["bitrate_kbps"], label="Baseline")
plt.plot(seg, pol2["bitrate_kbps"], label="Política 2")

for b, l in zip(bitrates, labels):
    plt.axhline(b, linestyle="--", alpha=0.2)
    plt.text(1, b + 30, l, fontsize=8, alpha=0.6)

plt.title("Comparação de Qualidade (Bitrate)")
plt.xlabel("Segmento")
plt.ylabel("kbps")
plt.legend()
plt.grid()
plt.xticks(range(2, n + 1, 2))
plt.show()

# =================================================
# 3. BUFFER
# =================================================
plt.figure(figsize=(10,5))

plt.plot(seg, pol1["buffer_s"], label="Baseline")
plt.plot(seg, pol2["buffer_level_s"], label="Política 2")

plt.title("Comparação de Buffer")
plt.xlabel("Segmento")
plt.ylabel("Segundos")
plt.legend()
plt.grid()
plt.xticks(range(2, n + 1, 2))
plt.show()


# =================================================
# 4. REBUFFER
# =================================================
plt.figure(figsize=(10,5))

plt.plot(seg, pol1["rebuffer_total_s"], label="Baseline")
plt.plot(seg, pol2["stall_duration_s"], label="Política 2")

plt.title("Comparação de Rebuffering")
plt.xlabel("Segmento")
plt.ylabel("Segundos acumulados")
plt.legend()
plt.grid()
plt.xticks(range(2, n + 1, 2))
plt.show()