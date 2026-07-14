import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { scopesApi } from '../api/scopes'
import { assetsApi } from '../api/assets'
import { ChevronRightIcon } from '../components/icons'
import AssetExplorer from '../components/AssetExplorer'

export default function ScopeContentPage() {
  const { scopeId } = useParams()

  const [scope, setScope] = useState(null)
  const [assetTotal, setAssetTotal] = useState(null)

  useEffect(() => {
    let active = true
    Promise.all([
      scopesApi.get(scopeId).catch(() => null),
      assetsApi.stats(scopeId).catch(() => null),
    ]).then(([s, st]) => {
      if (!active) return
      setScope(s)
      setAssetTotal(st?.total_assets ?? 0)
    })
    return () => {
      active = false
    }
  }, [scopeId])

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
        <span>Asset Explorer</span>
      </div>

      <header className="page-header">
        <div>
          <h1>Asset Explorer</h1>
          <p className="subtitle">
            {`${(assetTotal ?? 0).toLocaleString()} classified assets · organized by type`}
          </p>
        </div>
      </header>

      <AssetExplorer scopeId={scopeId} />
    </div>
  )
}
