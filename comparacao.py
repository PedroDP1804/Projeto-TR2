import pandas as pd
import matplotlib.pyplot as plt
import os

# --------------------------------------------------------------- #
#           Configuração dos Arquivos
# --------------------------------------------------------------- #
arquivos = {
    "T1 (Baseline)": "metricas_tarefa1.csv",
    "T2 (Buffer-Based)": "metricas_tarefa2.csv",
    "T3 (Híbrida Preditiva)": "metricas_tarefa3.csv"
}

dados = {}

# Lê os CSVs e padroniza os nomes das colunas e cálculos
for label, arquivo in arquivos.items():
    if os.path.exists(arquivo):
        df = pd.read_csv(arquivo)
        
        # Dicionário de tradução para igualar a T1 com a T2/T3
        colunas_renomeadas = {
            "segmento": "segment",
            "buffer_s": "buffer_level_s",
            "rebuffer_total_s": "stall_duration_s"
        }
        df = df.rename(columns=colunas_renomeadas)
        
        # Padroniza a métrica de travamento para ser acumulativa em todas
        if "stall_duration_s" in df.columns:
            if label == "T1 (Baseline)":
                # T1 já salva de forma acumulada
                df['rebuffer_acumulado'] = df['stall_duration_s']
            else:
                # T2 e T3 salvam por segmento, então somamos tudo (cumsum)
                df['rebuffer_acumulado'] = df['stall_duration_s'].cumsum()
                
        dados[label] = df
    else:
        print(f"<!> Arquivo {arquivo} não encontrado. Ele será ignorado no gráfico.")

if not dados:
    print("Nenhum arquivo CSV encontrado para gerar os gráficos.")
    exit()

# --------------------------------------------------------------- #
#           Geração dos Gráficos Comparativos
# --------------------------------------------------------------- #
fig, graficos = plt.subplots(nrows=3, ncols=1, figsize=(10, 12))
fig.suptitle("Comparação de Desempenho das Políticas ABR", fontsize=16, fontweight='bold')

cores = ["tab:blue", "tab:orange", "tab:green"]
marcadores = ["o", "s", "^"]

# Gráfico 1: Qualidade (Bitrate Escolhido)
for i, (label, df) in enumerate(dados.items()):
    if 'segment' in df.columns and 'bitrate_kbps' in df.columns:
        graficos[0].plot(df['segment'], df['bitrate_kbps'], label=label, color=cores[i], marker=marcadores[i], linewidth=2, alpha=0.8)
    
graficos[0].set_title("Qualidade de Vídeo Escolhida")
graficos[0].set_ylabel("Bitrate (kbps)")
graficos[0].grid(True, linestyle='--', alpha=0.6)
graficos[0].legend()

# Gráfico 2: Evolução do Nível do Buffer
for i, (label, df) in enumerate(dados.items()):
    if 'segment' in df.columns and 'buffer_level_s' in df.columns:
        graficos[1].plot(df['segment'], df['buffer_level_s'], label=label, color=cores[i], marker=marcadores[i], linewidth=2, alpha=0.8)

graficos[1].set_title("Nível do Buffer")
graficos[1].set_ylabel("Segundos no Tanque")
graficos[1].grid(True, linestyle='--', alpha=0.6)
graficos[1].legend()

# Gráfico 3: Duração dos Travamentos (Rebuffering)
for i, (label, df) in enumerate(dados.items()):
    if 'segment' in df.columns and 'rebuffer_acumulado' in df.columns:
        graficos[2].plot(df['segment'], df['rebuffer_acumulado'], label=label, color=cores[i], marker=marcadores[i], linewidth=2, alpha=0.8)

graficos[2].set_title("Tempo Total Acumulado de Travamento (Rebuffer)")
graficos[2].set_xlabel("Segmento")
graficos[2].set_ylabel("Segundos Travados")
graficos[2].grid(True, linestyle='--', alpha=0.6)
graficos[2].legend()

plt.tight_layout(rect=[0, 0, 1, 0.96])
plt.show()