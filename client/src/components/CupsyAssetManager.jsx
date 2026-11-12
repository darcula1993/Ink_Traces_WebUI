import React from 'react'
import CupsyLibrary from './library/CupsyLibrary'
// Compatibility entry for existing tools; all remote presentation uses the shared library grid.
export default function CupsyAssetManager({open,...props}){return open?<CupsyLibrary {...props}/>:null}
