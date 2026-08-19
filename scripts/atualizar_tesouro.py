"""
Baixa o CSV oficial de taxas/preços do Tesouro Direto (Tesouro Transparente),
extrai a Data Base mais recente (e a anterior, para calcular variação %% dia a dia)
e grava um JSON compacto (tesouro-cotacoes.json) para o Norte consumir via jsDelivr.

Roda dentro do GitHub Actions (server-to-server, sem problema de CORS).
"""
import csv
import json
import sys
import urllib.request
import urllib.error
from collections import defaultdict
from datetime import datetime, timezone

CSV_URL = (
    "https://www.tesourotransparente.gov.br/ckan/dataset/"
    "df56aa42-484a-4a59-8184-7676580c81e3/resource/"
    "796d2059-14e9-44e3-80c9-2d9e30b405c1/download/precotaxatesourodireto.csv"
)
OUT_PATH = "tesouro-cotacoes.json"


def parse_brl_number(s):
    s = (s or "").strip()
    if not s:
        return None
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def parse_date_br(s):
    return datetime.strptime(s.strip(), "%d/%m/%Y").date()


def chave_titulo(row):
    return (row[0].strip(), row[1].strip())  # (Tipo Titulo, Data Vencimento)


def baixar_csv():
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/csv,application/csv,text/plain,*/*",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    }
    req = urllib.request.Request(CSV_URL, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            status = getattr(resp, "status", resp.getcode())
            content_type = resp.headers.get("Content-Type", "?")
            data = resp.read()
    except urllib.error.HTTPError as e:
        print(f"ERRO HTTP {e.code} ao baixar o CSV: {e.reason}", file=sys.stderr)
        corpo = e.read()
        print("Primeiros 500 bytes da resposta de erro:", file=sys.stderr)
        print(corpo[:500], file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"ERRO DE REDE ao baixar o CSV: {e.reason}", file=sys.stderr)
        sys.exit(1)

    print(f"Download OK — status {status}, Content-Type: {content_type}, tamanho: {len(data)} bytes")
    return data.decode("utf-8", errors="replace")


def main():
    raw = baixar_csv()

    reader = csv.reader(raw.splitlines(), delimiter=";")
    cabecalho = next(reader, None)
    print(f"Cabeçalho lido: {cabecalho}")

    por_data = defaultdict(list)
    linhas_total = 0
    linhas_com_erro_data = 0
    for row in reader:
        linhas_total += 1
        if len(row) < 8:
            continue
        try:
            data_base = parse_date_br(row[2])
        except ValueError:
            linhas_com_erro_data += 1
            continue
        por_data[data_base].append(row)

    print(f"Linhas de dados processadas: {linhas_total} | com data inválida: {linhas_com_erro_data} | datas distintas encontradas: {len(por_data)}")

    if not por_data:
        print("Nenhum dado válido encontrado no CSV — abortando sem sobrescrever o JSON.", file=sys.stderr)
        print("Primeiros 500 caracteres do conteúdo baixado (para diagnóstico):", file=sys.stderr)
        print(raw[:500], file=sys.stderr)
        sys.exit(1)

    datas_ordenadas = sorted(por_data.keys())
    data_atual = datas_ordenadas[-1]
    data_anterior = datas_ordenadas[-2] if len(datas_ordenadas) > 1 else None

    linhas_atual = por_data[data_atual]
    linhas_anterior = por_data.get(data_anterior, []) if data_anterior else []
    anterior_por_chave = {chave_titulo(r): r for r in linhas_anterior}

    titulos = []
    for row in linhas_atual:
        tipo, vencimento, data_b, taxa_compra, taxa_venda, pu_compra, pu_venda, pu_base = row[:8]
        pu_venda_num = parse_brl_number(pu_venda)

        variacao_pct = None
        anterior = anterior_por_chave.get((tipo.strip(), vencimento.strip()))
        if anterior and pu_venda_num is not None:
            pu_venda_ant = parse_brl_number(anterior[6])
            if pu_venda_ant:
                variacao_pct = round((pu_venda_num - pu_venda_ant) / pu_venda_ant * 100, 4)

        titulos.append(
            {
                "tipo": tipo.strip(),
                "vencimento": vencimento.strip(),
                "dataBase": data_b.strip(),
                "taxaCompra": parse_brl_number(taxa_compra),
                "taxaVenda": parse_brl_number(taxa_venda),
                "puCompra": parse_brl_number(pu_compra),
                "puVenda": pu_venda_num,
                "puBase": parse_brl_number(pu_base),
                "variacaoPct": variacao_pct,
            }
        )

    payload = {
        "fonte": "Tesouro Transparente (tesourotransparente.gov.br) — precotaxatesourodireto.csv",
        "atualizadoEm": datetime.now(timezone.utc).isoformat(),
        "dataBase": data_atual.isoformat(),
        "dataBaseAnterior": data_anterior.isoformat() if data_anterior else None,
        "titulos": titulos,
    }

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"OK: {len(titulos)} título(s) gravado(s) em {OUT_PATH} (data base {data_atual.isoformat()})")


if __name__ == "__main__":
    main()
