import Big from 'big.js'

/** "0.00100000" -> "0.001": as many decimals as the value needs, never "1e-8". */
export function quantity(value: string): string {
  return new Big(value).toFixed()
}

/** "40100.06000000" -> "40,100.06" */
export function money(value: string, places = 2): string {
  const [whole, fraction] = new Big(value).toFixed(places).split('.')
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  return fraction === undefined ? grouped : `${grouped}.${fraction}`
}
