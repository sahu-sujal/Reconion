import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { scopesApi } from '../api/scopes'
import { assetsApi } from '../api/assets'
import { parametersApi } from '../api/parameters'
import { ChevronRightIcon } from '../components/icons'
import AssetExplorer from '../components/AssetExplorer'
import ParameterExplorer from '../components/ParameterExplorer'

export default function ScopeContentPage() {
  const { scopeId } = useParams()

  const [scope, setScope] = useState(null)
  const [assetTotal, setAssetTotal] = useState(null)
  const [paramTotal, setParamTotal] = useState(null)
  const [tab, setTab] = useState('assets') // 'assets' | 'parameters'

  useEffect(() => {
    let active = true
    Promise.all([
      scopesApi.get(scopeId).catch(() => null),
      assetsApi.stats(scopeId).catch(() => null),
      parametersApi.scopeStats(scopeId).catch(() => null),
    ]).then(([s, st, ps]) => {
      if (!active) return
      setScope(s)
      setAssetTotal(st?.total_assets ?? 0)
      setParamTotal(ps?.total_parameters ?? 0)
    })
    return () => {
      active = false
    }
  }, [scopeId])

  const crumbLabel = tab === 'parameters' ? 'Parameter Explorer' : 'Asset Explorer'

  return (
    <div className="page">
      <div className="breadcrumb">
        <Link to="/">Programs</Link>
        <ChevronRightIcon className="crumb-sep" width={14} height={14} />
        {scope?.program_id && (
          <>
            <Link to={`/programs/${scope.program_id}`}>Program</Link>
            <ChevronRightIcon className="crumb-sep" width={14} height={14} />
          </>
        )}
        <Link to={`/scopes/${scopeId}`}>{scope?.target}</Link>
        <ChevronRightIcon className="crumb-sep" width={14} height={14} />
        <span>{crumbLabel}</span>
      </div>

      <header className="page-header">
        <div>
          <h1>{crumbLabel}</h1>
          <p className="subtitle">
            {tab === 'parameters'
              ? `${(paramTotal ?? 0).toLocaleString()} discovered parameters · Arjun + ParamSpider`
              : `${(assetTotal ?? 0).toLocaleString()} classified assets · organized by type`}
          </p>
        </div>
      </header>

      {/* ---- Asset Explorer / Parameter Explorer tab switcher ---- */}
      <div className="content-tabs">
        <button
          type="button"
          className={`content-tab${tab === 'assets' ? ' active' : ''}`}
          onClick={() => setTab('assets')}
        >
          Asset Explorer
          <span className="content-tab-count">{(assetTotal ?? 0).toLocaleString()}</span>
        </button>
        <button
          type="button"
          className={`content-tab${tab === 'parameters' ? ' active' : ''}`}
          onClick={() => setTab('parameters')}
        >
          Parameters
          <span className="content-tab-count">{(paramTotal ?? 0).toLocaleString()}</span>
        </button>
      </div>

      {tab === 'assets' ? (
        <AssetExplorer scopeId={scopeId} />
      ) : (
        <ParameterExplorer scopeId={scopeId} />
      )}
    </div>
  )
}
