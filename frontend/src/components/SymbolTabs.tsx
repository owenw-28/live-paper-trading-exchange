interface Props {
  symbols: string[]
  selected: string
  onSelect: (symbol: string) => void
}

export function SymbolTabs({ symbols, selected, onSelect }: Props) {
  return (
    <div className="flex gap-1" role="tablist">
      {symbols.map((symbol) => (
        <button
          key={symbol}
          role="tab"
          aria-selected={symbol === selected}
          onClick={() => onSelect(symbol)}
          className={`rounded px-3 py-1 text-sm ${
            symbol === selected ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-white'
          }`}
        >
          {symbol}
        </button>
      ))}
    </div>
  )
}
