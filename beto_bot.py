beto-bot.py
import time
import pandas as pd
import requests
import os
import logging
import json
import traceback
from binance.client import Client
from binance.enums import *
from datetime import datetime

# 🔐 Credenciais via variáveis de ambiente
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

client = Client(API_KEY, API_SECRET)

# 📋 Configuração de logs
logging.basicConfig(
    filename='beto_bot.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# 🎯 Configurações de risco
VALOR_POR_OPERACAO = 6.00
STOP_PERCENTUAL = 1.5
PROFIT_PERCENTUAL = 3.0

# ⚙️ Configurações técnicas
MOEDAS_INTERESSANTES = ['BTCUSDT', 'ETHUSDT']
INTERVALO = '5m'
RSI_LIMITE_COMPRA = 40
RSI_LIMITE_VENDA = 70

# 🧠 Controle de posição com persistência
POSICOES_PATH = 'posicoes_abertas.json'

def carregar_posicoes():
    if os.path.exists(POSICOES_PATH):
        with open(POSICOES_PATH, 'r') as f:
            return json.load(f)
    return {}

def salvar_posicoes(posicoes):
    with open(POSICOES_PATH, 'w') as f:
        json.dump(posicoes, f)

posicoes_abertas = carregar_posicoes()

# 📲 Telegram
def enviar_telegram(mensagem):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': mensagem,
        'parse_mode': 'Markdown'
    }
    try:
        requests.post(url, data=payload)
    except Exception as e:
        logging.error(f"Erro ao enviar Telegram: {e}")

def buscar_dados(symbol):
    klines = client.get_klines(symbol=symbol, interval=INTERVALO, limit=100)
    df = pd.DataFrame(klines, columns=[
        'timestamp', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_asset_volume', 'number_of_trades',
        'taker_buy_base_volume', 'taker_buy_quote_volume', 'ignore'
    ])
    df['close'] = df['close'].astype(float)
    df['low'] = df['low'].astype(float)
    df['mm9'] = df['close'].rolling(window=9).mean()
    df['mm21'] = df['close'].rolling(window=21).mean()
    return df

def calcular_rsi(df, period=14):
    delta = df['close'].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1]

def cruzamento_mm(df):
    if df['mm9'].iloc[-2] < df['mm21'].iloc[-2] and df['mm9'].iloc[-1] > df['mm21'].iloc[-1]:
        return 'compra'
    elif df['mm9'].iloc[-2] > df['mm21'].iloc[-2] and df['mm9'].iloc[-1] < df['mm21'].iloc[-1]:
        return 'venda'
    else:
        return None

def calcular_quantidade(preco):
    return round(VALOR_POR_OPERACAO / preco, 6)

def comprar(symbol, preco, rsi):
    quantidade = calcular_quantidade(preco)
    try:
        client.create_order(
            symbol=symbol,
            side=SIDE_BUY,
            type=ORDER_TYPE_MARKET,
            quantity=quantidade
        )
        stop = preco * (1 - STOP_PERCENTUAL / 100)
        profit = preco * (1 + PROFIT_PERCENTUAL / 100)
        posicoes_abertas[symbol] = {
            'entrada': preco,
            'quantidade': quantidade,
            'stop': stop,
            'profit': profit
        }
        salvar_posicoes(posicoes_abertas)
        mensagem = (
            f"🟢 *COMPRA* `{symbol}`\n"
            f"Entrada: ${preco:.2f}\n"
            f"RSI: {rsi:.2f}\n"
            f"Valor operado: ${VALOR_POR_OPERACAO:.2f}\n"
            f"Stop: ${stop:.2f}\n"
            f"Profit: ${profit:.2f}\n"
            f"Qtd: {quantidade}\n"
            f"⏱ {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
        )
        enviar_telegram(mensagem)
        logging.info(mensagem)
    except Exception as e:
        enviar_telegram(f"⚠️ Erro ao comprar `{symbol}`: {e}")
        logging.error(traceback.format_exc())

def vender(symbol, preco, motivo):
    if symbol not in posicoes_abertas:
        return
    quantidade = posicoes_abertas[symbol]['quantidade']
    entrada = posicoes_abertas[symbol]['entrada']
    try:
        client.create_order(
            symbol=symbol,
            side=SIDE_SELL,
            type=ORDER_TYPE_MARKET,
            quantity=quantidade
        )
        resultado = preco - entrada
        percentual = (resultado / entrada) * 100
        mensagem = (
            f"🔴 *VENDA* `{symbol}`\n"
            f"Saída: ${preco:.2f}\n"
            f"Motivo: {motivo}\n"
            f"Valor operado: ${VALOR_POR_OPERACAO:.2f}\n"
            f"Resultado: {resultado:.2f} USD ({percentual:.2f}%)\n"
            f"⏱ {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
        )
        enviar_telegram(mensagem)
        logging.info(mensagem)
        del posicoes_abertas[symbol]
        salvar_posicoes(posicoes_abertas)
    except Exception as e:
        enviar_telegram(f"⚠️ Erro ao vender `{symbol}`: {e}")
        logging.error(traceback.format_exc())

def loop_principal():
    enviar_telegram("🤖 Beto-Bot iniciado com RSI + MM + Mínima + Stop/Profit.")
    while True:
        for symbol in MOEDAS_INTERESSANTES:
            try:
                df = buscar_dados(symbol)
                rsi = calcular_rsi(df)
                preco = float(client.get_symbol_ticker(symbol=symbol)['price'])
                cruzamento = cruzamento_mm(df)
                minima_3_candles = df['low'].tail(3).min()

                logging.info(f"[{symbol}] Preço: ${preco:.2f} | RSI: {rsi:.2f} | Cruzamento: {cruzamento} | Mínima: ${minima_3_candles:.2f}")

                if symbol not in posicoes_abertas:
                    if rsi < RSI_LIMITE_COMPRA and cruzamento == 'compra' and preco <= minima_3_candles * 1.01:
                        comprar(symbol, preco, rsi)
                else:
                    posicao = posicoes_abertas[symbol]
                    if preco <= posicao['stop']:
                        vender(symbol, preco, 'Stop Loss')
                    elif preco >= posicao['profit']:
                        vender(symbol, preco, 'Take Profit')
                    elif cruzamento == 'venda':
                        vender(symbol, preco, 'Cruzamento MM')

            except Exception as e:
                enviar_telegram(f"⚠️ Erro com `{symbol}`: {e}")
                logging.error(traceback.format_exc())
        time.sleep(60)

if __name__ == '__main__':
    loop_principal()
