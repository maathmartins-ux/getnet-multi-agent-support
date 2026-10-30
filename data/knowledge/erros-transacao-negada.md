---
title: Transação negada ou recusada na maquininha Getnet — causas, códigos e o que fazer
url: https://site.getnet.com.br/wp-content/uploads/2024/01/Manul_GetClassica.pdf
lang: pt
keywords: transação negada, transação recusada, não autorizada, cartão recusado, saldo insuficiente, senha incorreta, cartão bloqueado, emissor, decline, declined transaction, decline error, error code, ADQ, IDL, venda duplicada, chargeback, estorno
fetched_at: 2026-10-30
---
## Dois tipos de problema: erro técnico vs recusa do emissor

Quando uma transação é negada na maquininha Getnet, é preciso separar dois casos. Erro técnico: a maquininha Getnet mostra um código "ADQ", "IDL" ou "S-" e a culpa é de comunicação, configuração ou leitura; o lojista resolve pelo menu da maquininha. Recusa do emissor: a venda chega ao banco do cliente e volta como "não autorizada" (saldo, limite, senha, bloqueio); nesse caso só o cliente e o banco emissor resolvem.

## Causas comuns de transação negada pelo emissor

As causas mais frequentes de cartão recusado na maquininha Getnet são: saldo ou limite insuficiente; senha incorreta (após tentativas erradas o emissor bloqueia o cartão); cartão bloqueado, vencido, não desbloqueado ou cancelado; cartão sem a função escolhida (ex.: débito em cartão só crédito); bandeira não habilitada no contrato do lojista; cartão reportado como perdido ou roubado; e bloqueio preventivo do banco por suspeita de fraude ou compra fora do padrão. Em todos esses casos a Getnet não vê o motivo detalhado: o cliente deve ligar para o banco emissor.

## Códigos de erro ADQ e IDL da Getnet (manual oficial)

O manual oficial da Get Clássica e da Get Lite lista códigos de erro ADQ/IDL e a solução pelo menu de Função da maquininha Getnet (a tecla de Função varia por modelo: F ou #).

- ADQ 4-83 (integração com bandeiras), ADQ 4-91 (erro na aprovação da venda), ADQ 1-50 (erro de leitura), ADQ 4-30 (falha de comunicação), ADQ 4-23 (falha na transação), ADQ 4-27, IDL 1-04, IDL 1-36, S-2074, ADQ 1-02 (procedimento não finalizado): Função > 38 > Verde > Inicialização > Verde > venda teste.
- ADQ 1-21 (erro na transação), ADQ 3-30 (erro de criptografia após período sem uso), ADQ 1-33 (erro de leitura), ADQ 1-07 (não inicializada), IDL 1-08: Função > 60 > Verde > Configuração > Apagar memória > Senha do Técnico > Verde > Função 38 > Inicialização > Verde > venda teste.
- ADQ 1-06 (maquininha não configurada): Função > 90 > Verde > Função 38 > Verde > Configuração > Verde > Função 38 > Inicialização > venda teste.
- ADQ 1-87 (registro do chip): conferir chip inserido > Função > 25 > Senha do Lojista > Função 46 > Função 90 > venda teste.
- Erro na leitora NFC: Função > 82 > Senha do Operador > teste do teclado > teste do cartão > Função 38 > Inicialização > venda teste.

## Códigos de recusa do emissor (referência de mercado)

Os códigos de resposta do emissor não são publicados pela Getnet; a referência abaixo é do mercado de cartões (fonte secundária idinheiro.com.br) e vale como orientação geral: 05 / 51 / 22 = não autorizada ou saldo/limite insuficiente (cliente fala com o banco); 06 e 19 = falha passageira (tentar de novo); 14 e 16 = cartão inválido ou bloqueado; 43 = cartão perdido ou roubado (não devolva o cartão e confira identidade); 55 = senha incorreta; 03 e 11 = bandeira ou terminal incompatível. Em dúvida, anote o código exibido e pergunte à Central Getnet.

## Venda duplicada bloqueada

Na Get Smart (e em outras maquininhas Getnet), duas vendas idênticas (mesmo estabelecimento, cartão, bandeira e valor) em menos de 5 minutos fazem a segunda ser cancelada automaticamente como proteção contra duplicidade. Se a segunda venda era legítima, aguarde 5 minutos ou altere o valor em alguns centavos.

## O que o lojista deve fazer quando a transação é negada

1. Leia a mensagem no visor: se tiver código ADQ/IDL, aplique a solução do manual e faça uma venda teste; se disser "não autorizada", é recusa do emissor.
2. Tente novamente uma vez (pode ser falha passageira de comunicação).
3. Peça ao cliente para conferir senha, saldo/limite e se o cartão está desbloqueado, ou use outro cartão/forma de pagamento (Pix, débito).
4. Nunca force a venda por digitação para contornar a recusa: aumenta o risco de chargeback.
5. Se a recusa se repete com vários cartões, reinicie a maquininha e verifique a conexão; persistindo, ligue 4002-4000 / 4003-4000 (capitais) ou 0800-648-8000 (interior), ou WhatsApp 11 97694-6815.

## Chargeback: venda aprovada e depois cancelada

Segundo a central de ajuda da Getnet, chargeback é o cancelamento de uma transação após contestação do portador junto ao banco, com débito do valor na conta do lojista. Situações: mercadoria não entregue ou com defeito; transação não reconhecida pelo portador (em venda sem cartão presente pode ser cancelada mesmo com prova); processamento em duplicidade; estorno combinado mas não lançado; e cliente alega ter pago de outra forma. Guardar comprovantes e exigir senha reduz chargebacks.

## Summary (EN)

A declined transaction on a Getnet card machine is either a technical error, shown as an ADQ, IDL or S- code that the merchant fixes through the terminal's Function menu followed by a test sale, or an issuer decline ("não autorizada") caused by insufficient funds or credit limit, wrong PIN, blocked, expired or cancelled card, card lacking the chosen function, brand not enabled for the merchant, or a fraud block by the issuing bank. Getnet's official manual maps codes such as ADQ 4-83, 4-91, 4-30, 4-23, 1-21, 1-07, 1-06 and 1-87 to menu-based reinitialization steps.

Issuer response codes are not published by Getnet; market references treat 05/51 as insufficient funds, 55 as wrong PIN, 43 as lost or stolen card and 06/19 as temporary failure. The merchant should retry once, ask the customer to check with their bank or use another card or Pix, never key in the card to bypass a decline, and call Getnet support at 4002-4000 or 0800-648-8000 if declines persist across cards. Identical sales within 5 minutes are auto-cancelled as duplicates.
