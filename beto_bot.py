import time
import pandas as pd
import requests
import os
import json
from binance.client import Client
from binance.enums import *
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

client = Client(API_KEY, API_SECRET)

VALOR_POR_OPERACAO = 6.00
STOP_PERCENTUAL = 1.5
PROFIT_PERCENTUAL = 3.0
INTERVALO = '5m'
RSI_LIMITE_COMPRA = 40
VOLATILIDADE_MINIMA = 0.8

MOEDAS_ORIGINAIS = [
    'BTCUSDT', 'ETHUSDT', 'DOGEUSDT', 'SHIBUSDT', 'SOLUSDT',
    'BNBUSDT', 'XRPUSDT', 'OPUSDT', 'ARBUSDT', 'LINKUSDT',
    'INJUSDT', 'TIAUSDT', 'PYTHUSDT', 'JUPUSDT', 'RNDRUSDT',
    'LDOUSDT', 'BLZUSDT', 'COTIUSDT', 'SUIUSDT', 'APTUSDT',
    'MATICUSDT', 'AVAXUSDT', 'AAVEUSDT', 'UNIUSDT', 'DYDXUSDT',
    'MASKUSDT', 'GALAUSDT', 'ALGOUSDT', 'XLMUSDT', 'TRXUSDT',
    'NEARUSDT', 'STXUSDT', 'SKLUSDT', 'BICOUSDT', 'IDUSDT',
    'HOOKUSDT', 'SSVUSDT'
]

posicoes_abertas = {}
MOEDAS_VALIDAS = []

def enviar_telegram(mensagem):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': mensagem, 'parse_mode': 'Markdown'}
    try:
        requests.post(url, data=payload)
    except Exception as e:
        print(f"Erro ao enviar mensagem para Telegram: {e}")

def validar_moedas():
    global MOEDAS_VALIDAS
    MOEDAS_VALIDAS = []
    for symbol in MOEDAS_ORIGINAIS:
        try:
            client.get_symbol_ticker(symbol=symbol)
            MOEDAS_VALIDAS.append(symbol)
        except:
            enviar_telegram(f"⚠️ Ignorando símbolo inválido: `{symbol}`")
            print(f"Símbolo inválido: {symbol}")

def buscar_dados(symbol):
    klines = client.get_klines(symbol=symbol, interval=INTERVALO, limit=100)
    df = pd.DataFrame(klines, columns=[
        'timestamp', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_asset_volume', 'number_of_trades',
        'taker_buy_base_volume', 'taker_buy_quote_volume', 'ignore'
    ])
    df['close'] = df['close'].astype(float)
    df['low'] = df['low'].astype(float)
    df['high'] = df['high'].astype(float)
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

def volatilidade(df):
    high = df['high'].iloc[-1]
    low = df['low'].iloc[-1]
    return ((high - low) / low) * 100

def calcular_quantidade(preco):
    return round(VALOR_POR_OPERACAO / preco, 6)

def comprar(symbol, preco, rsi):
    quantidade = calcular_quantidade(preco)
    try:
        client.create_order(symbol=symbol, side=SIDE_BUY, type=ORDER_TYPE_MARKET, quantity=quantidade)
        stop = preco * (1 - STOP_PERCENTUAL / 100)
        profit = preco * (1 + PROFIT_PERCENTUAL / 100)
        posicoes_abertas[symbol] = {
            'entrada': preco,
            'quantidade': quantidade,
            'stop': stop,
            'profit': profit
        }
        mensagem = (
            f"🟢 *COMPRA* `{symbol}`\n"
            f"Entrada: ${preco:.4f}\nRSI: {rsi:.2f}\nQtd: {quantidade}\n"
            f"Stop: ${stop:.4f} | Profit: ${profit:.4f}\n"
            f"⏱ {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
        )
        enviar_telegram(mensagem)
        print(mensagem)
    except Exception as e:
        print(f"Erro ao comprar {symbol}: {e}")

def vender(symbol, preco, motivo):
    if symbol not in posicoes_abertas:
        return
    quantidade = posicoes_abertas[symbol]['quantidade']
    entrada = posicoes_abertas[symbol]['entrada']
    try:
        client.create_order(symbol=symbol, side=SIDE_SELL, type=ORDER_TYPE_MARKET, quantity=quantidade)
        resultado = preco - entrada
        percentual = (resultado / entrada) * 100
        mensagem = (
            f"🔴 *VENDA* `{symbol}`\n"
            f"Saída: ${preco:.4f}\nMotivo: {motivo}\n"
            f"Resultado: {resultado:.4f} USD ({percentual:.2f}%)\n"
            f"⏱ {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
        )
        enviar_telegram(mensagem)
        print(mensagem)
        del posicoes_abertas[symbol]
    except Exception as e:
        print(f"Erro ao vender {symbol}: {e}")

def loop_principal():
    print("✅ Beto-Bot iniciado com sucesso")
    enviar_telegram("🤖 Beto-Bot Turbo Silencioso iniciado. Monitorando o universo cripto.")
    validar_moedas()
    while True:
        for symbol in MOEDAS_VALIDAS:
            try:
                df = buscar_dados(symbol)
                rsi = calcular_rsi(df)
                preco = float(client.get_symbol_ticker(symbol=symbol)['price'])
                cruzamento = cruzamento_mm(df)
                minima_3 = df['low'].tail(3).min()
                vol = volatilidade(df)

                if symbol not in posicoes_abertas:
                    if rsi < RSI_LIMITE_COMPRA and cruzamento == 'compra' and preco <= minima_3 * 1.01 and vol >= VOLATILIDADE_MINIMA:
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
                print(f"Erro com {symbol}: {e}")
        time.sleep(60)

if __name__ == '__main__':
    loop_principal()
