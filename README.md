# 🔍 Agente de Licitações — Içara/Criciúma e Região

Agente automatizado no GitHub Actions que busca licitações públicas de **serviços** na região de Içara, Criciúma e municípios vizinhos em Santa Catarina, toda **segunda e quinta-feira às 8h**, e envia os resultados diretamente para um **canal do Telegram**.

## 🗓️ Agenda de execução

| Dia | Horário (Brasília) | Período coberto |
|-----|-------------------|-----------------|
| Segunda-feira | 08:00 | Últimos 4 dias (desde quinta anterior) |
| Quinta-feira  | 08:00 | Últimos 4 dias (desde segunda anterior) |

## 📍 Municípios cobertos

Içara · Criciúma · Morro da Fumaça · Cocal do Sul · Urussanga · Forquilhinha · Siderópolis · Nova Veneza

## 🌐 Fontes consultadas

| Portal | O que busca |
|--------|-------------|
| **PNCP** | Todas as contratações municipais (portal nacional) |
| **Portal SC** | Compras estaduais em SC |
| **TCE-SC / e-Sfinge** | Licitações fiscalizadas pelo Tribunal de Contas SC |
| **ComprasNet** | Órgãos federais na região (IFSC, INSS, CEF...) |
| **Prefeitura de Içara** | Site oficial |
| **Prefeitura de Criciúma** | Site oficial |

---

## ⚙️ Configuração — passo a passo

### 1. Criar o repositório no GitHub

```bash
git clone https://github.com/SEU_USUARIO/licitacoes-icara-criciuma
cd licitacoes-icara-criciuma
git push origin main
```

---

### 2. Criar o Bot do Telegram

1. Abra o Telegram e fale com **@BotFather**
2. Digite `/newbot` e siga as instruções
3. Copie o **Token** gerado (ex: `7123456789:AAF...`)
4. Crie um canal ou grupo e adicione o bot como **administrador**
5. Descubra o **Chat ID** do canal:
   - Para canal público: `@nome_do_canal`
   - Para grupo/canal privado: use `https://api.telegram.org/bot<TOKEN>/getUpdates` após enviar uma mensagem

---

### 3. Configurar Secrets no GitHub

No repositório: **Settings → Secrets and variables → Actions → New repository secret**

| Secret | Valor | Obrigatório |
|--------|-------|-------------|
| `TELEGRAM_BOT_TOKEN` | Token do BotFather (ex: `7123456789:AAF...`) | ✅ Sim |
| `TELEGRAM_CHAT_ID` | ID do canal/grupo (ex: `@meu_canal` ou `-100123456789`) | ✅ Sim |

---

### 4. Ativar o Actions e testar

1. Vá em **Actions** → clique em **"I understand my workflows, enable them"**
2. Clique em **"Busca de Licitações"** → **"Run workflow"** para executar agora
3. Aguarde ~3 minutos e verifique o canal do Telegram

---

## 📨 O que chega no Telegram

**Mensagem de texto** com resumo formatado:
```
📋 Segunda-feira, 19/05/2025
📍 Içara · Criciúma e região | SC

🔢 Total: 23 licitações de serviços
🔴 Urgentes (≤2 dias): 2
🟡 Esta semana:         8
🟢 Este mês:            13

🔴 URGENTES — encerram em até 2 dias

• Içara | Prefeitura Municipal de Içara
  Contratação de serviço de coleta de resíduos...
  💰 R$ 480.000,00 · 1d restantes
  🔗 Ver edital

...

📂 Planilha CSV completa em anexo
```

**Arquivo CSV** com todas as licitações anexado na mesma mensagem.

---

## 📊 Prioridades

| Ícone | Significado |
|-------|-------------|
| 🔴 URGENTE | Encerramento em ≤ 2 dias |
| 🟡 Esta semana | Encerramento em ≤ 7 dias |
| 🟢 Este mês | Encerramento em ≤ 30 dias |
| ⚪ Futuro | Sem data ou prazo longo |

---

## 🔧 Execução local (teste)

```bash
pip install -r requirements.txt

python src/buscar_pncp.py
python src/buscar_comprasnet.py
python src/buscar_portal_sc.py
python src/consolidar.py
python src/gerar_relatorio.py

# Testar envio manual ao Telegram
TOKEN="SEU_TOKEN"
CHAT="@seu_canal"
MSG=$(cat reports/telegram_resumo.txt)
curl -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
  -d chat_id="${CHAT}" -d parse_mode="HTML" --data-urlencode "text=${MSG}"
```

---

## ➕ Adicionar municípios

Edite a lista `MUNICIPIOS` em `src/buscar_pncp.py`:

```python
{"nome": "Novo Município", "codigo_ibge": "XXXXXXX", "uf": "SC"},
```

Código IBGE: https://cidades.ibge.gov.br/

---

## 📌 Links úteis

- [PNCP](https://pncp.gov.br) · [Portal SC](https://portaldecompras.sc.gov.br) · [TCE-SC](https://e-sfinge.tce.sc.gov.br)
- [Prefeitura Içara](https://www.icara.sc.gov.br/licitacoes) · [Prefeitura Criciúma](https://www.criciuma.sc.gov.br/site/licitacoes)
- [BotFather no Telegram](https://t.me/BotFather)

---
*Desenvolvido com GitHub Actions + Python | Roda toda segunda e quinta às 8h (Brasília)*
