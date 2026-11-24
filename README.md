# Replay for pump.fun bots

A bot that trades new coins on pump.fun can win on paper and lose with real money, because paper fills at the price on the screen, and a real order lands later, moves the price itself, pays fees and sometimes fails. The replay at [replay.loopholetape.com](https://replay.loopholetape.com/) takes the picks a bot made, or would have made, and says what each would really have brought: it puts the bot's buy where it would have landed after the bot's own delay, prices it on the reserves of that moment with the bonding curve's own arithmetic, walks forward through the trades that really followed until the sell rule fires, and carries a position on into the coin's pool when the coin leaves the curve.

This repository holds a small client for it, an example and the description of its routes. The service itself runs at the address above, and its engine is not in this repository.

## Try it without a wallet

The first pick of any document is replayed for free, and a document can be checked for free before that.

```
curl -s -X POST https://replay.loopholetape.com/v1/check -d @example_picks.json
curl -s -X POST https://replay.loopholetape.com/v1/replay/first -d @example_picks.json
```

The same two steps with the client in this repository, which needs Python and one package (`pip install solders`):

```
python replay_client.py check example_picks.json
python replay_client.py sample example_picks.json
```

## The picks document

```json
{"settings": {"delay_ms": 800, "placement": "last", "priority_fee": 12000, "tip": 10000},
 "picks": [{"id": "my-first-pick",
            "mint": "THE_COIN_MINT_ADDRESS",
            "decision": 1795359229,
            "stake_lamports": 100000000,
            "slippage_bps": 1500,
            "exit": {"type": "threshold", "up_bps": 3000, "down_bps": 2000, "max_seconds": 60}}]}
```

A pick names the coin by its mint address, the moment the bot decided, the SOL it would put in with fees included, the slippage it allows in hundredths of a percent, and the rule by which it sells, which is either a holding time (`{"type": "time", "seconds": 30}`) or a rise and a fall with a time limit. The moment is a Unix time in whole seconds, which means the start of that second, or `{"slot": S, "index": I}`, which means directly after the transaction at that position in the slot. The settings give the bot's delay from deciding to landing, where in its landing slot the order sits (`last`, `first` or `after_trigger`), and what it pays as priority fee and tip in lamports. Each pick is replayed by itself, so two picks on the same coin do not feel each other. The file [openapi.json](openapi.json) holds the full schema.

## A full run

A full run replays up to 50 picks for 1 USDC, and each pick may look up to 60 minutes ahead for its exit. It is paid by the bot's own wallet over [x402](https://www.x402.org/) with USDC on Solana: the service answers a request that carries no payment with status 402 and its terms, a client signs one transfer for exactly that amount and sends the request again. The wallet needs only the USDC, because the service that settles the payment pays the network fee.

```
python replay_client.py buy my_picks.json --keypair ~/bot-wallet.json
```

The client signs nothing above the `--max-usdc` you give it (1 by default) and pays no address but the one the service is paid at, `9HkwyUhDMyjbpSpnyu5xuZ9vRaFQeajnJsavhie7XcsT`. Read it before you give it a key, and use a wallet that holds little. Any other x402 client that speaks the second version of the protocol with plain USDC on Solana works as well, as long as its owner lets it spend 1 USDC in one payment, which is the standard client's own ceiling.

A run is charged when at least one of its picks could be priced at its entry, which includes a buy that would have failed on its own limit, because that failure is the answer. A document that is wrong, a pick whose exit window ended less than a minute ago, a run in which no pick could be priced, a run that takes longer than half a minute and every failure on our side are answered with a status of 400 or more and are not charged. Every paid answer is kept for 7 days, so a buyer whose answer did not arrive fetches it again with a signature of the paying wallet:

```
python replay_client.py results --keypair ~/bot-wallet.json
```

## For an agent

The notes for agents are at [replay.loopholetape.com/llms.txt](https://replay.loopholetape.com/llms.txt), and the free check and the free sample are also offered as tools at `https://replay.loopholetape.com/mcp`, which speaks the Model Context Protocol over HTTP.

## What it assumes, and where it can be wrong

The replay inserts your order and keeps everyone else's orders as they were: every other buyer still spends the SOL they really spent and every other seller still sells the tokens they really sold, and what each of them gets is worked out again on the changed reserves. Real traders might have acted differently once your order was there. Where exactly a real order lands inside a block is not known beforehand, so the answer holds for the place you chose in the settings. An order can also fail for reasons the replay does not model, above all a transaction that never lands at a launch, where most transactions fail. A coin whose curve is priced in something other than SOL is recognised and not replayed.

## How it was checked

The arithmetic was checked against the chain before anything else was built. On seventeen coins it reproduces 8,424 of 8,425 real fills on the bonding curve exactly, in the amounts and in both fees, with the one remaining fill a single lamport apart in a fee, and all 3,452 real fills in the pools exactly. The checker's own output is at [replay.loopholetape.com/validation.txt](https://replay.loopholetape.com/validation.txt).

## Who runs it

A small project called loopholetape runs the replay, and an AI agent that works for the person behind the project wrote it and operates it, which we say plainly because a reader should know. It is a calculation on public records and no advice on what to trade, and it is not connected to pump.fun. Questions and corrections reach us at hello@agent.loopholetape.com. The client and the example in this repository are under the MIT licence.
