# ⚡ LicitaBot — Analisador de Licitações Públicas com IA

Bot completo para monitorar o PNCP (Portal Nacional de Contratações Públicas),
analisar editais automaticamente com IA (Claude) e enviar alertas via Telegram.

---

## 🗂 Estrutura do projeto

```
licitacoes_bot/
├── coletor_pncp.py     # Coleta licitações da API do PNCP
├── analisador_ia.py    # Analisa editais com a API do Claude
├── bot_telegram.py     # Bot Telegram para alertas e consultas
├── agendador.py        # Orquestra tudo + API REST (FastAPI)
├── database.py         # Banco de dados SQLite
├── dashboard.html      # Interface web do dashboard
├── requirements.txt    # Dependências Python
└── .env.example        # Variáveis de ambiente (modelo)
```

---

## 🚀 Instalação passo a passo

### 1. Pré-requisitos

- Python 3.10 ou superior
- Conta na Anthropic (para a API do Claude): https://console.anthropic.com
- (Opcional) Bot no Telegram: fale com @BotFather

### 2. Clone e instale

```bash
# Crie uma pasta e entre nela
mkdir licitacoes_bot && cd licitacoes_bot

# (Recomendado) Crie um ambiente virtual
python -m venv venv
source venv/bin/activate        # Linux/macOS
venv\Scripts\activate           # Windows

# Instale as dependências
pip install -r requirements.txt
```

### 3. Configure as variáveis de ambiente

```bash
cp .env.example .env
```

Abra o arquivo `.env` e preencha:

| Variável | Onde obter |
|---|---|
| `ANTHROPIC_API_KEY` | https://console.anthropic.com/settings/keys |
| `TELEGRAM_BOT_TOKEN` | Fale com @BotFather no Telegram → /newbot |
| `TELEGRAM_CHAT_IDS` | Fale com @userinfobot no Telegram |

### 4. Inicialize o banco de dados

```bash
python database.py
# Output: ✅ Banco de dados inicializado.
```

### 5. Teste a coleta

```bash
# Coleta licitações do último dia (todos os estados)
python coletor_pncp.py 1

# Coleta licitações dos últimos 3 dias, filtrando SC e PR
python coletor_pncp.py 3 SC,PR
```

### 6. Teste a análise com IA

```bash
# Analisa todas as licitações sem análise no banco
python analisador_ia.py

# Analisa uma licitação específica pelo ID
python analisador_ia.py 1
```

---

## ▶️ Modos de execução

### Modo único (coleta + análise uma vez)

```bash
python agendador.py
```

### Modo daemon (roda automaticamente a cada N horas)

```bash
python agendador.py --daemon
```

### API REST (para o dashboard)

```bash
uvicorn agendador:api --host 0.0.0.0 --port 8000 --reload
```

Acesse: http://localhost:8000/docs (documentação automática)

### Bot Telegram

```bash
python bot_telegram.py
```

### Dashboard web

Abra o arquivo `dashboard.html` diretamente no navegador.

Para conectar ao backend real, garanta que a API está rodando em `localhost:8000`.

---

## 📡 Endpoints da API REST

| Método | Rota | Descrição |
|---|---|---|
| GET | `/licitacoes` | Lista licitações com filtros |
| GET | `/licitacoes/{id}` | Detalhes de uma licitação + análise |
| GET | `/stats` | Estatísticas gerais |
| POST | `/ciclo` | Dispara ciclo manual de coleta+análise |

### Parâmetros de `/licitacoes`

```
?score_minimo=65    # Score mínimo da análise IA (0-100)
?uf=SC              # Filtrar por estado
?sem_analise=true   # Só licitações sem análise
?limit=20           # Quantidade por página
?offset=0           # Paginação
```

### Exemplo de uso

```bash
# Busca oportunidades com score >= 70 em SC
curl "http://localhost:8000/licitacoes?score_minimo=70&uf=SC"

# Dispara ciclo manualmente
curl -X POST "http://localhost:8000/ciclo"
```

---

## 🤖 Comandos do Bot Telegram

| Comando | Descrição |
|---|---|
| `/start` | Apresentação e lista de comandos |
| `/oportunidades` | Top oportunidades com alto score |
| `/recentes` | Licitações recentes coletadas |
| `/stats` | Estatísticas gerais do bot |
| `/ajuda` | Como funciona o bot |

O bot também envia alertas automáticos quando encontra uma licitação
com score acima do limite configurado (`SCORE_MINIMO_ALERTA`).

---

## ⚙️ Personalização

### Filtros de coleta (`coletor_pncp.py`)

```python
FILTROS = {
    "palavras_chave": ["software", "TI", "consultoria"],  # Edite aqui
    "valor_minimo": 10_000,
    "valor_maximo": 5_000_000,
    "estados": ["SC", "RS", "PR"],  # [] = todos os estados
    "modalidades": [],               # [] = todas as modalidades
}
```

### Perfil da empresa (`analisador_ia.py`)

```python
PERFIL_EMPRESA = {
    "nome": "Minha Empresa Ltda",
    "segmentos": ["Desenvolvimento de software", "Consultoria em TI"],
    "certidoes_disponiveis": ["CND Federal", "FGTS", "CNDT"],
    "faturamento_anual_reais": 500_000,
    ...
}
```

Quanto mais detalhado o perfil, mais precisa será a análise da IA.

---

## 🔄 Execução em produção (Linux com systemd)

### Serviço do agendador (daemon)

Crie o arquivo `/etc/systemd/system/licitabot.service`:

```ini
[Unit]
Description=LicitaBot — Analisador de Licitações
After=network.target

[Service]
Type=simple
User=seu_usuario
WorkingDirectory=/caminho/para/licitacoes_bot
EnvironmentFile=/caminho/para/licitacoes_bot/.env
ExecStart=/caminho/para/venv/bin/python agendador.py --daemon
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable licitabot
sudo systemctl start licitabot
sudo systemctl status licitabot
```

### API REST como serviço

```ini
[Unit]
Description=LicitaBot API REST
After=network.target

[Service]
Type=simple
User=seu_usuario
WorkingDirectory=/caminho/para/licitacoes_bot
EnvironmentFile=/caminho/para/licitacoes_bot/.env
ExecStart=/caminho/para/venv/bin/uvicorn agendador:api --host 0.0.0.0 --port 8000
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

---

## 🛠 Troubleshooting

### "Nenhuma licitação encontrada"
- Verifique se os filtros de palavras-chave são muito restritivos
- Tente rodar com `dias_atras=7` para um período maior
- Confirme conexão com a internet (API do PNCP pode ter instabilidades)

### "Erro na análise IA: 401"
- Verifique se `ANTHROPIC_API_KEY` está correto no `.env`
- Confirme que a variável está sendo carregada: `echo $ANTHROPIC_API_KEY`

### "Bot Telegram não responde"
- Verifique se `TELEGRAM_BOT_TOKEN` está correto
- Confirme que o bot está rodando: `python bot_telegram.py`
- Verifique se seu `CHAT_ID` está na lista de autorizados

### Banco de dados corrompido
```bash
# Recria o banco do zero
rm licitacoes.db
python database.py
```

---

## 📊 Fluxo completo

```
                    ┌─────────────────────────────────┐
                    │          PNCP API                │
                    │  pncp.gov.br/api/pncp/v1        │
                    └────────────┬────────────────────┘
                                 │ httpx (async)
                                 ▼
                    ┌─────────────────────────────────┐
                    │       coletor_pncp.py            │
                    │  Filtra por palavras-chave,      │
                    │  valor, estado e modalidade      │
                    └────────────┬────────────────────┘
                                 │ salva no banco
                                 ▼
                    ┌─────────────────────────────────┐
                    │         database.py              │
                    │       SQLite / PostgreSQL        │
                    └────────────┬────────────────────┘
                                 │ busca sem análise
                                 ▼
                    ┌─────────────────────────────────┐
                    │       analisador_ia.py           │
                    │  Envia edital para Claude API    │
                    │  Retorna score + recomendação    │
                    └────────────┬────────────────────┘
                                 │ score >= mínimo?
                        ┌────────┴────────┐
                        ▼                 ▼
           ┌────────────────────┐  ┌─────────────────────┐
           │   bot_telegram.py  │  │    dashboard.html    │
           │  Alerta automático │  │   Interface visual   │
           │  + consultas /cmd  │  │   + API FastAPI      │
           └────────────────────┘  └─────────────────────┘
```

---

## 📜 Licença

MIT — use, modifique e distribua livremente.

---

*Desenvolvido com Claude (Anthropic) + API PNCP (dados públicos)*
