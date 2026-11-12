import React from 'react'
import {createPortal} from 'react-dom'
import SidebarMenu from './SidebarMenu'

// A portal keeps the glass sidebar's backdrop-filter/overflow from clipping menus.
export default function SidebarNavigationMenu({maxWidth,...props}){
 return createPortal(<div className="canvas-studio cv-sidebar-menu-portal" style={{'--cv-nav-menu-max-width':`${maxWidth}px`}}><SidebarMenu {...props}/></div>,document.body)
}
