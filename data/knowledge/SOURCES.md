# SOURCES — corpus Getnet Brasil

Data de coleta: 2026-10-30 (13:22–13:35, horário de São Paulo). Ferramentas: WebFetch, WebSearch, extração de PDF com pypdf.

## Achado principal

`https://www.getnet.net/` e `https://www.getnet.net/en` são o site **global** (Getnet Europe/LatAm): só posicionamento institucional, sem produto brasileiro. O site **brasileiro oficial** é `https://site.getnet.com.br/`, linkado a partir do seletor de país do site global. Todo o conteúdo de produto veio de lá e de seus PDFs.

## Fontes oficiais Getnet (primárias)

| URL | Usado em | Observação |
|---|---|---|
| https://site.getnet.com.br/ | taxas-planos, comparativo, atendimento, pix, link | Home BR; tabela de taxas "a partir de", preços das maquininhas (campanha Black Friday ativa), telefones, horário 06h–22h |
| https://site.getnet.com.br/todas-as-maquininhas/ | comparativo, taxas-planos, get-smart | Mensalidades PJ (Clássica 79,90 / Smart 129,90), faixas de isenção (20k/40k/80k); conteúdo truncado; horário divergente (seg–sex 7h–23h, sáb 9h–15h) |
| https://site.getnet.com.br/pix/ | pix, prazos | "Receba em segundos", aviso de até 1 dia corrido, formas de Pix |
| https://site.getnet.com.br/duvidas/pix/ | pix, prazos | FAQ: chaves, contratação, elegibilidade (domicílio Santander) |
| https://site.getnet.com.br/duvidas/ | prazos, antecipacao, conta-digital, troubleshooting, atendimento | Índice da central de ajuda + trechos de prazos, chip Algar, Get Conta |
| https://site.getnet.com.br/duvidas/antecipacao-de-vendas/ | antecipacao | FAQ: D+1 a D-3, canais, gravame/cessão, horários |
| https://site.getnet.com.br/duvidas/aluguel/ | taxas-planos, comparativo | FAQ isenção: bandeiras válidas, não cumulativo, antecipação automática como contrapartida |
| https://site.getnet.com.br/duvidas/parcelado/ | crediario-parcelamento, prazos | Parcelado emissor (24x) vs lojista (12x, D+31) |
| https://site.getnet.com.br/crediario/ | crediario-parcelamento | Até 48x, emissor define, lojista recebe em 2 dias úteis |
| https://site.getnet.com.br/link-de-pagamento/ | link-de-pagamento | Planos Inicial/Básico, criação, canais, prazos pré-pago |
| https://site.getnet.com.br/duvidas/get-smart/ | get-smart, erros | FAQ Get Smart: Getstore, bateria, duplicidade 5 min, NFC |
| https://site.getnet.com.br/duvidas/operacional/ | troubleshooting, erros | Ligar/desligar por modelo, estorno, chargeback |
| https://site.getnet.com.br/conta-digital/ | conta-digital | Página de marketing; detalhes vieram do FAQ /duvidas/ |
| https://site.getnet.com.br/get-ajuda/ | atendimento | Canais e URLs de ajuda |
| https://site.getnet.com.br/wp-content/uploads/2024/01/Manul_GetClassica.pdf | get-classica, troubleshooting, erros, atendimento | Manual oficial (16 p.) extraído com pypdf: bateria 4–8h, chip 3G, Wi-Fi, tabela de erros ADQ/IDL, Pix exige domicílio Santander, Central "24 horas" |
| https://site.getnet.com.br/wp-content/uploads/2026/07/getnet_19_06-26_Manul_GetLite_V4-1.pdf | comparativo, troubleshooting | Manual Get Lite (15 p.) extraído com pypdf; Central "06h às 22h" |
| https://site.getnet.com.br/wp-content/uploads/2019/12/SUMARIO-EXECUTIVO-DO-CONTRATO-DE-ADESAO-AO-SISTEMA-GETNET.pdf | antecipacao | Via snippet de busca: automática contratada na adesão ou Central; eventual pelo POS/canais |
| https://site.getnet.com.br/wp-content/uploads/2025/08/getnet_relatorio_ouvidori_2025_V2.pdf | atendimento | Via snippet: Central 24h/7d, mesmos telefones |
| https://www.getnet.net/ e https://www.getnet.net/en | — | Fetch OK, mas sem conteúdo de produto BR (site global) |

## Fontes secundárias

| URL | Usado em | Observação |
|---|---|---|
| https://www.calculadoradetaxas.com.br/getnet/taxas | taxas-planos, pix, prazos | Comparador de terceiros, atualizado 01/10/2026: Pix "grátis", faixas PJ, Get Lite R$ 94,80. Marcado como secundário no texto |
| https://www.santander.com.br/blog/seus-negocios/pix-na-maquina-getnet/ | pix | **403 no fetch**; citado só pelo snippet de busca (artigo de 2022, menciona taxa Pix para PJ — desatualizado) |
| https://www.santander.com/en/press-room/press-releases/2024/10/getnet-by-santander-launches-getnet-sep... | ecommerce | Comunicado Santander sobre Getnet SEP (via home global) |
| https://www.idinheiro.com.br/negocios/codigos-erro-cartao/ | erros | Códigos de recusa genéricos do mercado (não Getnet); marcado no texto |
| https://www.idinheiro.com.br/negocios/maquina-de-cartao-fora-do-ar/ | troubleshooting | Passos genéricos (reiniciar, roteador) |

## URLs que falharam

- https://www.getnet.net/maquininhas — 404 (não existe; site global)
- https://site.getnet.com.br/maquininhas/ — retornou PNG (imagem), sem texto
- https://www.santander.com.br/blog/seus-negocios/pix-na-maquina-getnet/ — 403
- https://www.santander.com.br/blog/ativacao-maquininha-getnet — 403
- https://www.santander.com.br/blog/isencao-aluguel-maquininha — 403
- https://site.getnet.com.br/wp-content/uploads/2024/01/Manul_GetMini.pdf — não baixado por tempo (citado via snippet para o caminho Wi-Fi da Get Mini)

## Lacunas (sem fonte oficial confiável)

1. **Taxa do Pix** — site oficial não publica; fontes divergem (grátis vs 1,40% vs "taxa para PJ" em 2022). Texto manda consultar o site oficial.
2. **Taxa de antecipação (%)** — não publicada; só "não incluída na simulação".
3. **Especificações de hardware da Get Smart** (processador, 4G, bateria em mAh) — página oficial não traz.
4. **Preço/condição atual da Get Lite** — só em comparador de terceiros.
5. **Get Mobile e SuperGet** — não existem como maquininha no site atual; SuperGet é nome do app. Registrado no comparativo.
6. **Número máximo de parcelas do Link de Pagamento** — não informado na página.
7. **Horário da Central** — três versões oficiais (06h–22h; 24h; seg–sex 7h–23h/sáb 9h–15h). Adotado 06h–22h (home + manual Get Lite 2026) com nota de divergência.
8. **Prazo de repasse diferente para contas de outros bancos** — nenhuma fonte; registrado que Pix exige domicílio Santander ou Get Conta.
9. **Códigos de recusa do emissor** — Getnet não publica; usados códigos genéricos de mercado, sinalizados como tal.
10. **Valor da taxa de adesão do comodato** — PDF existe, valor não extraído.
