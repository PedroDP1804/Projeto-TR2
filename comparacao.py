import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import os

# --------------------------------------------------------------- #
#           Configuração e Leitura dos Arquivos
# --------------------------------------------------------------- #
arquivos = {
    "T1 (Rate-Based)": "metricas_tarefa1.csv",
    "T2 (Buffer-Based)": "metricas_tarefa2.csv",
    "T3 (Híbrida Preditiva)": "metricas_tarefa3.csv"
}

dados = {}
bitrates_map = {}

for label, arquivo in arquivos.items():
    if os.path.exists(arquivo):
        df = pd.read_csv(arquivo)
        
        # 1. Padronização de Colunas (T1 vs T2/T3)
        if "segmento" in df.columns:
            df = df.rename(columns={
                "segmento": "segment",
                "buffer_s": "buffer_level_s",
                "rebuffer_total_s": "stall_duration_s",
                "throughput_kbps": "vazao_kbps",
                "jitter_s": "jitter_network_ms",
                "qualidade": "quality"
            })  
                
        # 2. Identificação de Eventos de Rebuffering
        if "rebuffer_event" not in df.columns:
            if label == "T1 (Rate-Based)" and "stall_duration_s" in df.columns:
                # Na T1 o stall_duration é acumulado, então travou se o valor subiu
                df["rebuffer_event"] = (df["stall_duration_s"].diff() > 0).astype(int)
                if df["stall_duration_s"].iloc[0] > 0:
                    df.loc[0, "rebuffer_event"] = 1
            else:
                df["rebuffer_event"] = 0
                
        # 3. Tratamento do Jitter EWMA (Garante que exista em todos para comparação)
        df["jitter_network_ms"] = pd.to_numeric(df["jitter_network_ms"], errors='coerce').fillna(0)
        if "jitter_ewma_ms" not in df.columns or df["jitter_ewma_ms"].astype(str).str.contains('null').any():
            # Aplica o filtro EWMA (alpha=0.125) retroativamente se a coluna não existir
            df["jitter_ewma_ms"] = df["jitter_network_ms"].ewm(alpha=0.125, adjust=False).mean()
        else:
            df["jitter_ewma_ms"] = pd.to_numeric(df["jitter_ewma_ms"], errors='coerce').fillna(0)

        # 4. Mapeamento de Qualidades para o eixo Y
        if "bitrate_kbps" in df.columns and "quality" in df.columns:
            for b, q in zip(df["bitrate_kbps"], df["quality"]):
                bitrates_map[b] = q

        dados[label] = df
    else:
        print(f"<!> Arquivo {arquivo} não encontrado.")

if not dados:
    print("Nenhum arquivo CSV encontrado. Execute os clientes primeiro.")
    exit()

# Ordena o mapeamento de qualidades para o gráfico
bitrates_lista = sorted(list(bitrates_map.keys())) if bitrates_map else [200, 400, 800, 1200, 2400, 4800]
qualidades_lista = [bitrates_map.get(b, f"{b}k") for b in bitrates_lista]

# --------------------------------------------------------------- #
#           Geração do Painel Comparativo (3x3)
# --------------------------------------------------------------- #
# 3 linhas (Métricas), 3 colunas (Políticas), compartilhando o eixo Y por linha
fig, axes = plt.subplots(nrows=3, ncols=3, figsize=(18, 12), sharey='row', sharex=True)
fig.suptitle("Comparação de Políticas ABR: Baseline vs Buffer-Based vs Híbrida Preditiva", fontsize=18, fontweight='bold', y=0.98)

SEGMENTO_FAILOVER = 10
labels_politicas = list(dados.keys())

for col_idx, label in enumerate(labels_politicas):
    df = dados[label]
    segmentos = df['segment']
    # --- LINHA 0: Vazão Medida + Qualidade Selecionada ---
    ax_vazao = axes[0, col_idx]
    ax_vazao.set_title(f"{label}", fontsize=14, fontweight='bold', color='darkblue')
    
    # Plot de AMBOS no mesmo eixo principal para partilharem a escala real
    ax_vazao.plot(segmentos, df['vazao_kbps'], color='tab:blue', label="Vazão Medida", linewidth=2, alpha=0.6)
    ax_vazao.plot(segmentos, df['bitrate_kbps'], color='tab:orange', label="Qualidade Selecionada", linewidth=3, drawstyle='steps-post')
    
    # Efeito visual premium: preenche a área abaixo da qualidade
    ax_vazao.fill_between(segmentos, df['bitrate_kbps'], color='tab:orange', alpha=0.15, step='post')
    
    ax_vazao.set_ylabel("Largura de Banda (kbps)") if col_idx == 0 else None
    ax_vazao.grid(True, linestyle='--', alpha=0.5)
    ax_vazao.axvline(x=SEGMENTO_FAILOVER, color='red', linestyle='--', linewidth=1.5, label="Failover")
    ax_vazao.legend(loc='lower right', fontsize=9)
    
    # Truque para as etiquetas "1080p", "720p" aparecerem corretamente à direita
    ax_labels = ax_vazao.twinx()
    ax_labels.set_ylim(ax_vazao.get_ylim()) # Obriga a régua direita a ser idêntica à esquerda
    if col_idx == 2: # Só mostra os textos "1080p" na última coluna
        ax_labels.set_yticks(bitrates_lista)
        ax_labels.set_yticklabels(qualidades_lista)
    else:
        ax_labels.set_yticks([]) # Mantém limpo nas outras colunas

    # --- LINHA 1: Nível do Buffer + Marcação de Rebuffering ---
    ax_buffer = axes[1, col_idx]
    ax_buffer.plot(segmentos, df['buffer_level_s'], color='tab:green', linewidth=2, label="Nível do Buffer (s)")
    ax_buffer.set_ylabel("Buffer (segundos)") if col_idx == 0 else None
    ax_buffer.grid(True, linestyle='--', alpha=0.5)
    
    # Marcação visual de onde o vídeo travou (Rebuffering)
    travamentos = df[df['rebuffer_event'] == 1]
    if not travamentos.empty:
        ax_buffer.scatter(travamentos['segment'], travamentos['buffer_level_s'], color='red', s=100, marker='X', zorder=5, label="Travamento (Rebuffer)")
    
    ax_buffer.legend(loc='upper left')
    ax_buffer.axvline(x=SEGMENTO_FAILOVER, color='red', linestyle='--', linewidth=1.5)


    # --- LINHA 2: Variação de Atraso (Jitter) EWMA ---
    ax_jitter = axes[2, col_idx]
    ax_jitter.plot(segmentos, df['jitter_ewma_ms'], color='purple', linewidth=2, label="Jitter EWMA")
    
    # Plot opcional do Jitter bruto esfumaçado no fundo para mostrar como o EWMA limpa o ruído
    ax_jitter.plot(segmentos, df['jitter_network_ms'], color='purple', linewidth=1, alpha=0.2, label="Jitter Bruto")
    
    ax_jitter.set_xlabel("Segmento", fontsize=12)
    ax_jitter.set_ylabel("Atraso (ms)") if col_idx == 0 else None
    ax_jitter.grid(True, linestyle='--', alpha=0.5)
    ax_jitter.legend(loc='upper right')
    ax_jitter.axvline(x=SEGMENTO_FAILOVER, color='red', linestyle='--', linewidth=1.5)

# Evita a sobreposição e ajusta os espaçamentos das bordas
plt.tight_layout(pad=2.0, w_pad=1.0, h_pad=2.0)
fig.subplots_adjust(top=0.92) # Dá espaço para o título principal
plt.show()