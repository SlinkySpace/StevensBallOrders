'use client'

/**
 * The Catalog Manager: prices, stock, visibility, imports and one-offs.
 *
 * Every write here is one call onto a db.py function through the API, which is
 * what keeps this page from becoming a second implementation of the catalog
 * rules. The import in particular only ever sends the file: parsing it and
 * deciding what is new is the API's job, because those rules are the ones
 * sync_catalog and the scraper already use.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Chrome } from '@/components/Chrome'
import { useApp } from '@/app/providers'
import {
  api, type AdminCatalog, type Freshness, type ImportMode, type ImportPreview,
  type Product, type ProductEdit,
} from '@/lib/api'
import { catalogToCsv, currency, downloadCsv, imageSrc } from '@/lib/format'

const PER_PAGE = 25
const STORM_URL_MARKER = 'stormbowling.com'

const TABS = [
  { key: 'products', label: 'Products' },
  { key: 'import', label: 'Import from scraper CSV' },
  { key: 'add', label: 'Add / remove' },
] as const

type TabKey = (typeof TABS)[number]['key']

export default function ManagerPage() {
  return <Chrome><Manager /></Chrome>
}

function Manager() {
  const { isAdmin, loading, notify } = useApp()
  const [catalog, setCatalog] = useState<AdminCatalog | null>(null)
  const [fresh, setFresh] = useState<Freshness | null>(null)
  const [tab, setTab] = useState<TabKey>('products')

  const load = useCallback(async () => {
    try {
      const [next, freshness] = await Promise.all([
        api.adminCatalog(),
        api.freshness().catch(() => null),
      ])
      setCatalog(next)
      setFresh(freshness)
    } catch (error: unknown) {
      notify(error instanceof Error ? error.message : 'Could not load the catalog.', 'bad')
    }
  }, [notify])

  useEffect(() => { if (isAdmin) void load() }, [isAdmin, load])

  if (loading) {
    return (
      <main className="wrap">
        <div style={{ fontSize: 13, color: 'var(--dim2)' }}>Loading…</div>
      </main>
    )
  }

  if (!isAdmin) {
    return (
      <main className="wrap">
        <div className="empty">
          <div className="empty__icon">🔒</div>
          <div className="empty__title">Owners only.</div>
          <div className="empty__body">Ask a captain if you need catalog access.</div>
        </div>
      </main>
    )
  }

  const counts = catalog?.counts

  return (
    <main className="wrap">
      <h1 className="h1">Catalog Manager</h1>
      <p className="sub">Price and stock changes show up for everyone on their next page load.</p>

      <div className="tiles">
        <Tile label="Products" value={counts ? String(counts.total) : '—'} />
        <Tile label="In stock" value={counts ? String(counts.in_stock) : '—'} />
        <Tile label="Visible to shoppers" value={counts ? String(counts.visible) : '—'} />
        <Tile label="Last imported" value={fresh?.age ?? '—'}
              accent={Boolean(fresh?.stale)} />
      </div>

      {fresh?.stale && (
        <div className="warn" style={{ marginBottom: 22 }}>
          <span style={{ fontSize: 16 }}>⚠️</span>
          <div>
            The catalog was last refreshed {fresh.age}. Storm&apos;s sponsor prices change;
            re-run the scraper and import the CSV below.
          </div>
        </div>
      )}

      <div className="tabs">
        {TABS.map((item) => (
          <button key={item.key} onClick={() => setTab(item.key)}
                  className={tab === item.key ? 'tab tab--on' : 'tab'}>{item.label}</button>
        ))}
      </div>

      {catalog === null ? (
        <div style={{ fontSize: 13, color: 'var(--dim2)' }}>Loading the catalog…</div>
      ) : tab === 'products' ? (
        <ProductsTab catalog={catalog} onSaved={load} />
      ) : tab === 'import' ? (
        <ImportTab onImported={load} />
      ) : (
        <AddRemoveTab catalog={catalog} onChanged={load} />
      )}

      <style>{`
        .wrap { max-width: 1320px; margin: 0 auto; padding: 36px 28px 80px; }
        .tiles {
          display: grid; grid-template-columns: repeat(4, minmax(0, 1fr));
          gap: 14px; margin-bottom: 16px;
        }
        .tabs {
          display: flex; gap: 4px; padding: 4px; background: var(--bg2);
          border: 1px solid var(--border); border-radius: 10px; margin-bottom: 22px;
          overflow-x: auto;
        }
        .tab {
          padding: 10px 14px; border: 0; border-radius: 7px; cursor: pointer;
          white-space: nowrap; background: transparent; color: var(--dim);
          font: 700 13px/1 'Source Sans 3', sans-serif;
        }
        .tab--on { background: var(--card); color: var(--text); box-shadow: 0 1px 3px rgba(0,0,0,0.10); }
        .warn {
          display: flex; gap: 12px; padding: 14px 18px; font-size: 14px; line-height: 1.55;
          border: 1px solid rgba(214,158,46,0.4); background: rgba(214,158,46,0.11);
          border-radius: 12px;
        }
        @media (max-width: 900px) {
          .wrap { padding: 24px 16px 64px; }
          .tiles { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        }
      `}</style>
    </main>
  )
}

function Tile({ label, value, accent = false }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className="card" style={{ padding: '16px 18px' }}>
      <div className="stat-label">{label}</div>
      <div className={accent ? 'stat-value stat-value--accent' : 'stat-value'}>{value}</div>
    </div>
  )
}

/* --- products ------------------------------------------------------------ */

type Draft = { price?: string; in_stock?: boolean; is_visible?: boolean }

function ProductsTab({ catalog, onSaved }: { catalog: AdminCatalog; onSaved: () => Promise<void> }) {
  const { notify } = useApp()
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('')
  const [stock, setStock] = useState('')
  const [page, setPage] = useState(1)
  const [drafts, setDrafts] = useState<Record<string, Draft>>({})
  const [busy, setBusy] = useState(false)

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase()
    return catalog.products.filter((product) => {
      if (category && product.sub_category !== category) return false
      if (stock === 'in' && !product.in_stock) return false
      if (stock === 'out' && product.in_stock) return false
      if (!needle) return true
      return product.name.toLowerCase().includes(needle)
        || String(product.sku ?? '').toLowerCase().includes(needle)
    })
  }, [catalog.products, search, category, stock])

  useEffect(() => { setPage(1) }, [search, category, stock])

  const totalPages = Math.max(1, Math.ceil(filtered.length / PER_PAGE))
  const current = Math.min(page, totalPages)
  const shown = filtered.slice((current - 1) * PER_PAGE, (current - 1) * PER_PAGE + PER_PAGE)
  const pending = Object.keys(drafts).length

  function edit(product: Product, patch: Draft) {
    setDrafts((prev) => ({ ...prev, [product.product_url]: { ...prev[product.product_url], ...patch } }))
  }

  function valueOf(product: Product) {
    const draft = drafts[product.product_url] ?? {}
    return {
      price: draft.price ?? Number(product.price).toFixed(2),
      in_stock: draft.in_stock ?? product.in_stock,
      is_visible: draft.is_visible ?? product.is_visible,
    }
  }

  async function save() {
    const updates: ProductEdit[] = Object.entries(drafts).map(([product_url, draft]) => {
      const update: ProductEdit = { product_url }
      if (draft.price !== undefined) {
        const price = Number(draft.price)
        if (Number.isFinite(price) && price >= 0) update.price = price
      }
      if (draft.in_stock !== undefined) update.in_stock = draft.in_stock
      if (draft.is_visible !== undefined) update.is_visible = draft.is_visible
      return update
    }).filter((update) => Object.keys(update).length > 1)

    if (!updates.length) {
      notify('Nothing to save — check the prices are numbers.', 'bad')
      return
    }

    setBusy(true)
    try {
      const result = await api.updateProducts(updates)
      setDrafts({})
      await onSaved()
      notify(`Updated ${result.updated} product${result.updated === 1 ? '' : 's'}.`)
    } catch (error: unknown) {
      notify(error instanceof Error ? error.message : 'Could not save those edits.', 'bad')
    } finally {
      setBusy(false)
    }
  }

  async function bulkStock(inStock: boolean) {
    if (!filtered.length) return
    setBusy(true)
    try {
      const result = await api.setStock(filtered.map((p) => p.product_url), inStock)
      await onSaved()
      notify(`${result.updated} product${result.updated === 1 ? '' : 's'} marked ${inStock ? 'in' : 'out of'} stock.`)
    } catch (error: unknown) {
      notify(error instanceof Error ? error.message : 'Could not change stock.', 'bad')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <div className="filters">
        <input className="field" value={search} onChange={(e) => setSearch(e.target.value)}
               placeholder="Filter by name or SKU" />
        <select className="field" value={category} onChange={(e) => setCategory(e.target.value)}
                style={{ cursor: 'pointer' }}>
          <option value="">All categories</option>
          {catalog.sub_categories.map((name) => <option key={name} value={name}>{name}</option>)}
        </select>
        <select className="field" value={stock} onChange={(e) => setStock(e.target.value)}
                style={{ cursor: 'pointer' }}>
          <option value="">Any stock</option>
          <option value="in">In stock only</option>
          <option value="out">Out of stock only</option>
        </select>
      </div>

      <div style={{ fontSize: 13, color: 'var(--dim)', margin: '0 0 14px' }}>
        {filtered.length} of {catalog.counts.total} products. Edit cells, then press
        {' '}<strong style={{ color: 'var(--text)' }}>Save changes</strong>. Un-ticking
        {' '}<strong style={{ color: 'var(--text)' }}>Visible</strong> hides a product from
        shoppers immediately.
      </div>

      <div className="card" style={{ overflowX: 'auto' }}>
        <div className="grid grid--head">
          <div />
          <div>Product</div><div>SKU</div><div className="right">Price</div>
          <div className="center">In stock</div><div className="center">Visible</div>
          <div>Category</div><div>Type</div>
        </div>
        {shown.map((product) => {
          const value = valueOf(product)
          const src = imageSrc(product.image_url)
          const dirty = Boolean(drafts[product.product_url])
          return (
            <div className="grid grid--row" key={product.product_url}
                 style={dirty ? { background: 'var(--soft)' } : undefined}>
              <div>
                {src
                  // eslint-disable-next-line @next/next/no-img-element
                  ? <img src={src} alt="" style={{
                      width: 34, height: 34, objectFit: 'contain', borderRadius: 6,
                      background: 'rgba(128,128,128,0.06)',
                    }} />
                  : <div style={{ width: 34, height: 34, borderRadius: 6, background: 'rgba(128,128,128,0.06)' }} />}
              </div>
              <div title={product.name} style={{
                minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis',
                whiteSpace: 'nowrap', fontWeight: 600,
              }}>{product.name}</div>
              <div className="mono" style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {product.sku || '—'}
              </div>
              <div>
                <input className="field field--sm" inputMode="decimal" value={value.price}
                       onChange={(e) => edit(product, { price: e.target.value })}
                       style={{ textAlign: 'right' }} />
              </div>
              <div className="center">
                <input type="checkbox" checked={value.in_stock}
                       onChange={(e) => edit(product, { in_stock: e.target.checked })}
                       style={{ width: 16, height: 16, accentColor: 'var(--primary)', cursor: 'pointer' }} />
              </div>
              <div className="center">
                <input type="checkbox" checked={value.is_visible}
                       onChange={(e) => edit(product, { is_visible: e.target.checked })}
                       style={{ width: 16, height: 16, accentColor: 'var(--primary)', cursor: 'pointer' }} />
              </div>
              <div style={{ color: 'var(--dim)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {product.sub_category}
              </div>
              <div className="mono">{product.product_type}</div>
            </div>
          )
        })}
        {!shown.length && (
          <div style={{ padding: 20, fontSize: 13, color: 'var(--dim2)' }}>
            Nothing matches those filters.
          </div>
        )}
      </div>

      {totalPages > 1 && (
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          gap: 16, marginTop: 16,
        }}>
          <button className="btn-quiet" disabled={current <= 1}
                  onClick={() => setPage(current - 1)}>← Previous</button>
          <div style={{ fontSize: 13, color: 'var(--dim)' }}>Page {current} of {totalPages}</div>
          <button className="btn-quiet" disabled={current >= totalPages}
                  onClick={() => setPage(current + 1)}>Next →</button>
        </div>
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginTop: 16, flexWrap: 'wrap' }}>
        <button className="btn" onClick={save} disabled={!pending || busy}>
          {busy ? 'Saving…' : 'Save changes'}
        </button>
        <div style={{ fontSize: 13, color: 'var(--dim)' }}>
          {pending ? `${pending} unsaved change${pending === 1 ? '' : 's'}.` : 'No unsaved changes.'}
        </div>
      </div>

      <div style={{ marginTop: 28, paddingTop: 24, borderTop: '1px solid var(--border)' }}>
        <div style={{ font: '700 15px/1 Archivo, sans-serif', marginBottom: 6 }}>Bulk stock update</div>
        <div style={{ fontSize: 13, color: 'var(--dim)', marginBottom: 14 }}>
          Applies to every product currently shown by the filters above.
        </div>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <button className="btn-quiet" disabled={busy || !filtered.length}
                  onClick={() => bulkStock(true)}>Mark all {filtered.length} in stock</button>
          <button className="btn-quiet" disabled={busy || !filtered.length}
                  onClick={() => bulkStock(false)}>Mark all {filtered.length} out of stock</button>
          <button className="btn-quiet"
                  onClick={() => downloadCsv('catalog_export.csv', catalogToCsv(filtered))}>
            Download catalog CSV
          </button>
        </div>
      </div>

      <style>{`
        .filters {
          display: grid; grid-template-columns: minmax(0, 2fr) minmax(0, 1fr) minmax(0, 1fr);
          gap: 12px; margin-bottom: 12px;
        }
        .grid {
          display: grid; gap: 10px; align-items: center;
          grid-template-columns: 48px minmax(200px, 2.2fr) 110px 96px 78px 74px 150px 110px;
          min-width: 1020px;
        }
        .grid--head {
          padding: 11px 16px; background: var(--bg2); border-bottom: 1px solid var(--border);
          font: 600 10px/1 'Source Sans 3', sans-serif; letter-spacing: 0.08em;
          text-transform: uppercase; color: var(--dim);
        }
        .grid--row { padding: 9px 16px; border-bottom: 1px solid var(--border); font-size: 13px; }
        .center { text-align: center; }
        @media (max-width: 900px) { .filters { grid-template-columns: 1fr; } }
      `}</style>
    </div>
  )
}

/* --- import -------------------------------------------------------------- */

const MODES: { value: ImportMode; label: string }[] = [
  { value: 'add_new', label: 'Add new products only' },
  { value: 'refresh', label: 'Refresh prices, stock and details (keeps hidden products hidden)' },
  { value: 'replace', label: 'Replace the whole Storm catalog' },
]

function ImportTab({ onImported }: { onImported: () => Promise<void> }) {
  const { notify } = useApp()
  const [csv, setCsv] = useState('')
  const [filename, setFilename] = useState('')
  const [mode, setMode] = useState<ImportMode>('refresh')
  const [preview, setPreview] = useState<ImportPreview | null>(null)
  const [showChanges, setShowChanges] = useState(false)
  const [busy, setBusy] = useState(false)

  // The preview depends on the mode - replace matches on URL where the others
  // also match on SKU - so it is re-run whenever either changes.
  useEffect(() => {
    if (!csv) { setPreview(null); return }
    let cancelled = false
    setBusy(true)
    api.previewImport(csv, mode)
      .then((next) => { if (!cancelled) setPreview(next) })
      .catch((error: unknown) => {
        if (cancelled) return
        setPreview(null)
        notify(error instanceof Error ? error.message : 'Could not read that file.', 'bad')
      })
      .finally(() => { if (!cancelled) setBusy(false) })
    return () => { cancelled = true }
  }, [csv, mode, notify])

  async function apply() {
    setBusy(true)
    try {
      const result = await api.applyImport(csv, mode)
      setCsv('')
      setFilename('')
      setPreview(null)
      await onImported()
      notify(`Import complete — ${result.inserted} added, ${result.updated} updated, ${result.deleted} removed.`)
    } catch (error: unknown) {
      notify(error instanceof Error ? error.message : 'The import failed.', 'bad')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ maxWidth: 820 }}>
      <div style={{ fontSize: 14, lineHeight: 1.6, color: 'var(--dim)', marginBottom: 20 }}>
        Re-run <code className="mono">storm_scraper.py</code> then
        {' '}<code className="mono">label_cleaning.py</code> when Storm changes their line-up,
        and upload the resulting CSV here. No commit, no redeploy.
      </div>

      <label style={{
        display: 'block', border: '1px dashed var(--border)', borderRadius: 14,
        background: 'var(--bg2)', padding: 34, textAlign: 'center', marginBottom: 22,
        cursor: 'pointer',
      }}>
        <div style={{ fontSize: 26, marginBottom: 10 }}>📄</div>
        <div style={{ font: '700 15px/1.3 Archivo, sans-serif', marginBottom: 5 }}>
          {filename || 'Choose a scraper CSV'}
        </div>
        <div style={{ fontSize: 13, color: 'var(--dim)' }}>
          {preview
            ? `${preview.rows} usable product rows`
            : 'Same columns as storm_products_tagged.csv'}
        </div>
        <input type="file" accept=".csv,text/csv" style={{ display: 'none' }}
               onChange={async (e) => {
                 const file = e.target.files?.[0]
                 if (!file) return
                 setFilename(file.name)
                 setCsv(await file.text())
               }} />
      </label>

      {preview && (
        <>
          <div className="tiles3">
            <Tile label="New products" value={String(preview.new)} />
            <Tile label="Already in catalog" value={String(preview.existing)} />
            <Tile label="In catalog but not in file" value={String(preview.missing)} />
          </div>

          <div className="card" style={{ overflow: 'hidden', margin: '14px 0 22px' }}>
            <button onClick={() => setShowChanges(!showChanges)} style={{
              width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '14px 18px', background: 'transparent', border: 0, color: 'var(--text)',
              font: "600 14px/1 'Source Sans 3', sans-serif", cursor: 'pointer', textAlign: 'left',
            }}>
              <span>{preview.price_changes.length} price change{preview.price_changes.length === 1 ? '' : 's'} in this file</span>
              <span style={{ color: 'var(--dim2)', fontSize: 11 }}>{showChanges ? '▲' : '▼'}</span>
            </button>
            {showChanges && preview.price_changes.length > 0 && (
              <div className="rows" style={{ border: 0, borderTop: '1px solid var(--border)', borderRadius: 0 }}>
                <div className="rows__head" style={{ gridTemplateColumns: 'minmax(0, 2fr) 120px 120px' }}>
                  <div>Product</div><div className="right">Current</div><div className="right">New</div>
                </div>
                {preview.price_changes.map((change) => (
                  <div className="rows__row" key={change.product_url}
                       style={{ gridTemplateColumns: 'minmax(0, 2fr) 120px 120px' }}>
                    <div style={{ fontWeight: 600 }}>{change.name}</div>
                    <div className="right num" style={{ color: 'var(--dim)' }}>{currency(change.from)}</div>
                    <div className="right num" style={{ fontWeight: 700 }}>{currency(change.to)}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}

      <label className="label">How should this file be applied?</label>
      <div style={{ display: 'grid', gap: 9, margin: '0 0 18px' }}>
        {MODES.map((option) => {
          const active = mode === option.value
          return (
            <button key={option.value} onClick={() => setMode(option.value)} style={{
              display: 'flex', alignItems: 'center', gap: 11, textAlign: 'left', width: '100%',
              padding: '13px 16px', borderRadius: 10, cursor: 'pointer',
              font: "600 14px/1.35 'Source Sans 3', sans-serif",
              background: active ? 'var(--soft)' : 'var(--card)',
              color: active ? 'var(--text)' : 'var(--dim)',
              border: `1px solid ${active ? 'rgba(163,38,56,0.4)' : 'var(--border)'}`,
            }}>
              <span style={{
                width: 14, height: 14, borderRadius: '50%', flex: 'none',
                background: active ? 'var(--primary)' : 'transparent',
                boxShadow: active ? 'inset 0 0 0 3px var(--card)' : 'none',
                border: active ? 'none' : '1px solid var(--border)',
              }} />
              <span>{option.label}</span>
            </button>
          )
        })}
      </div>

      {mode === 'replace' && (
        <div className="warn" style={{ marginBottom: 18 }}>
          <span style={{ fontSize: 16 }}>⚠️</span>
          <div>
            Replace drops every Storm product first, so anything Storm has stopped listing
            disappears. Products you added by hand and any hidden flags survive. Past orders
            are not affected.
          </div>
        </div>
      )}

      <button className="btn" onClick={apply} disabled={!csv || busy || !preview}>
        {busy ? 'Working…' : 'Apply import'}
      </button>

      <style>{`
        .tiles3 { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }
        .warn {
          display: flex; gap: 12px; padding: 14px 18px; font-size: 14px; line-height: 1.55;
          border: 1px solid rgba(214,158,46,0.4); background: rgba(214,158,46,0.11);
          border-radius: 12px;
        }
        @media (max-width: 700px) { .tiles3 { grid-template-columns: 1fr; } }
      `}</style>
    </div>
  )
}

/* --- add / remove -------------------------------------------------------- */

function AddRemoveTab({ catalog, onChanged }: {
  catalog: AdminCatalog; onChanged: () => Promise<void>
}) {
  const { notify } = useApp()
  const [form, setForm] = useState({
    name: '', sku: '', price: '0', main_category: 'Merchandise',
    sub_category: 'Apparel', product_type: 'general', image_url: '', product_url: '',
  })
  const [selected, setSelected] = useState<string[]>([])
  const [busy, setBusy] = useState(false)

  // Hand-added products are the ones whose URL is not a Storm one - the same
  // rule a replace import uses to decide what it may safely delete.
  const removable = useMemo(
    () => catalog.products.filter((p) => !p.product_url.includes(STORM_URL_MARKER)),
    [catalog.products],
  )

  function set(field: keyof typeof form, value: string) {
    setForm((prev) => ({ ...prev, [field]: value }))
  }

  async function add() {
    setBusy(true)
    try {
      await api.addProduct({
        product_url: form.product_url.trim(),
        name: form.name.trim(),
        sku: form.sku.trim(),
        price: Number(form.price) || 0,
        main_category: form.main_category.trim() || 'Merchandise',
        sub_category: form.sub_category.trim() || 'Apparel',
        product_type: form.product_type,
        image_url: form.image_url.trim(),
      })
      setForm({
        name: '', sku: '', price: '0', main_category: 'Merchandise',
        sub_category: 'Apparel', product_type: 'general', image_url: '', product_url: '',
      })
      await onChanged()
      notify('Product added.')
    } catch (error: unknown) {
      notify(error instanceof Error ? error.message : 'Could not add that product.', 'bad')
    } finally {
      setBusy(false)
    }
  }

  async function remove() {
    if (!selected.length) return
    setBusy(true)
    try {
      const result = await api.deleteProducts(selected)
      setSelected([])
      await onChanged()
      notify(`Deleted ${result.deleted} product${result.deleted === 1 ? '' : 's'}.`)
    } catch (error: unknown) {
      notify(error instanceof Error ? error.message : 'Could not delete those.', 'bad')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ maxWidth: 820 }}>
      <div style={{ fontSize: 14, color: 'var(--dim)', marginBottom: 20 }}>
        For anything not in the Storm catalog — club shirts, raffle items, one-offs.
      </div>

      <div className="card" style={{ padding: 22, marginBottom: 28 }}>
        <div className="pair">
          <div>
            <label className="label">Product name</label>
            <input className="field" value={form.name} onChange={(e) => set('name', e.target.value)} />
          </div>
          <div>
            <label className="label">Main category</label>
            <input className="field" value={form.main_category}
                   onChange={(e) => set('main_category', e.target.value)} />
          </div>
          <div>
            <label className="label">SKU</label>
            <input className="field" value={form.sku} onChange={(e) => set('sku', e.target.value)} />
          </div>
          <div>
            <label className="label">Sub category</label>
            <input className="field" value={form.sub_category}
                   onChange={(e) => set('sub_category', e.target.value)} />
          </div>
          <div>
            <label className="label">Price</label>
            <input className="field" inputMode="decimal" value={form.price}
                   onChange={(e) => set('price', e.target.value)} />
          </div>
          <div>
            <label className="label">Type</label>
            <select className="field" value={form.product_type} style={{ cursor: 'pointer' }}
                    onChange={(e) => set('product_type', e.target.value)}>
              <option value="general">general</option>
              <option value="bowling_ball">bowling_ball</option>
              <option value="apparel">apparel</option>
            </select>
          </div>
        </div>

        <div style={{ marginTop: 16 }}>
          <label className="label">Image URL (optional)</label>
          <input className="field" value={form.image_url}
                 onChange={(e) => set('image_url', e.target.value)} />
        </div>

        <div style={{ margin: '16px 0 18px' }}>
          <label className="label">Reference</label>
          <input className="field" value={form.product_url} placeholder="club-warmup-2026"
                 onChange={(e) => set('product_url', e.target.value)} />
          <div style={{ fontSize: 12, color: 'var(--dim2)', marginTop: 6 }}>
            Any unique string. It is the product&apos;s key, and keeping it off
            stormbowling.com is what stops a catalog import from touching it.
          </div>
        </div>

        <button className="btn" onClick={add}
                disabled={busy || !form.name.trim() || !form.product_url.trim()}>
          {busy ? 'Working…' : 'Add product'}
        </button>
      </div>

      <div style={{ font: '700 15px/1 Archivo, sans-serif', marginBottom: 6 }}>Remove products</div>
      <div style={{ fontSize: 13, color: 'var(--dim)', marginBottom: 14 }}>
        Hiding is usually better than deleting — untick <strong style={{ color: 'var(--text)' }}>Visible</strong>
        {' '}on the Products tab. Only hand-added products are listed here; Storm&apos;s own come
        back on the next import anyway.
      </div>

      <div className="card" style={{ padding: 16 }}>
        {removable.length === 0 ? (
          <div style={{ fontSize: 13, color: 'var(--dim2)' }}>Nothing added by hand yet.</div>
        ) : (
          <>
            <label className="label">Products to delete permanently</label>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 14 }}>
              {removable.map((product) => {
                const active = selected.includes(product.product_url)
                return (
                  <button key={product.product_url} onClick={() => setSelected(
                    active
                      ? selected.filter((url) => url !== product.product_url)
                      : [...selected, product.product_url],
                  )} style={{
                    padding: '8px 13px', borderRadius: 999, cursor: 'pointer',
                    font: "600 12px/1 'Source Sans 3', sans-serif",
                    background: active ? 'var(--soft)' : 'var(--bg2)',
                    color: active ? 'var(--ink)' : 'var(--dim)',
                    border: `1px solid ${active ? 'rgba(163,38,56,0.4)' : 'var(--border)'}`,
                  }}>{product.name}</button>
                )
              })}
            </div>
            <button className="btn-quiet" onClick={remove} disabled={!selected.length || busy}
                    style={selected.length ? { color: 'var(--ink)', borderColor: 'var(--ink)' } : undefined}>
              {selected.length ? `Delete ${selected.length} product${selected.length === 1 ? '' : 's'}` : 'Delete products'}
            </button>
          </>
        )}
      </div>

      <style>{`
        .pair { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
        @media (max-width: 700px) { .pair { grid-template-columns: 1fr; } }
      `}</style>
    </div>
  )
}
