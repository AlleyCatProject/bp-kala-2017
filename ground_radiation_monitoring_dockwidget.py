# -*- coding: utf-8 -*-
"""
/***************************************************************************
 GroundRadiationMonitoringDockWidget
                                 A QGIS plugin
 This plugin calculates the amount of received radiation. 
                             -------------------
        begin                : 2017-01-10
        git sha              : $Format:%H$
        copyright            : (C) 2017 by Michael Kala
        email                : michael.kala@email.cz
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

import os

from PyQt4.QtCore import QSettings, QTranslator, qVersion, QCoreApplication, Qt, QFileInfo
from PyQt4.QtGui import QComboBox, QAction, QIcon, QToolButton, QFileDialog
from qgis.core import QgsMapLayerRegistry, QgsMapLayer, QGis, QgsPoint, QgsRaster, QgsProject,  QgsProviderRegistry, QgsDistanceArea
from qgis.utils import QgsMessageBar, iface
from qgis.gui import QgsMapLayerComboBox,QgsMapLayerProxyModel
from osgeo import gdal, ogr
from math import ceil
from array import array

from PyQt4 import QtGui, uic
from PyQt4.QtCore import pyqtSignal

from ground_radiation_monitoring_computation import GroundRadiationMonitoringComputation

FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'ground_radiation_monitoring_dockwidget_base.ui'))


class GroundRadiationMonitoringDockWidget(QtGui.QDockWidget, FORM_CLASS):

    closingPlugin = pyqtSignal()

    def __init__(self, parent=None):
        """Constructor."""
        super(GroundRadiationMonitoringDockWidget, self).__init__(parent)
        # Set up the user interface from Designer.
        # After setupUI you can access any designer object by doing
        # self.<objectname>, and you can use autoconnect slots - see
        # http://qt-project.org/doc/qt-4.8/designer-using-a-ui-file.html
        # #widgets-and-dialogs-with-auto-connect
        self.setupUi(self)

        self.settings = QSettings("CTU","GRMplugin")

        self.iface = iface

        # Set filters for QgsMapLayerComboBoxes
        self.raster_box.setFilters(QgsMapLayerProxyModel.RasterLayer)
        self.track_box.setFilters(QgsMapLayerProxyModel.LineLayer)

        self.load_raster.clicked.connect(self.onLoadRaster)
        self.load_track.clicked.connect(self.onLoadTrack)

        self.save_button.setEnabled(False)
        self.dir_button.clicked.connect(self.onDirButton)
        self.save_button.clicked.connect(self.onExportRasterValues)

    def closeEvent(self, event):
        self.closingPlugin.emit()
        event.accept()

    def onLoadRaster(self):
        """Open 'Add raster layer dialog'."""
        sender = '{}-lastUserFilePath'.format(self.sender().objectName())
        lastUsedFilePath = self.settings.value(sender, '')

        fileName = QFileDialog.getOpenFileName(self,self.tr(u'Open raster'), 
                                               self.tr(u'{}').format(lastUsedFilePath),
                                               QgsProviderRegistry.instance().fileRasterFilters())
        if fileName:
            self.iface.addRasterLayer(fileName, QFileInfo(fileName).baseName())
            self.settings.setValue(sender, os.path.dirname(fileName))


    def onLoadTrack(self):
        """Open 'Add track layer dialog'."""
        sender = '{}-lastUserFilePath'.format(self.sender().objectName())
        lastUsedFilePath = self.settings.value(sender, '')
        
        fileName = QFileDialog.getOpenFileName(self,self.tr(u'Open track'),
                                               self.tr(u'{}').format(lastUsedFilePath), 
                                               QgsProviderRegistry.instance().fileVectorFilters())
        if fileName:
            self.iface.addVectorLayer(fileName, QFileInfo(fileName).baseName(), "ogr")
            self.settings.setValue(sender, os.path.dirname(fileName))

            # TODO: make this work for multiple layer loading
            if self.iface.activeLayer().geometryType() != QGis.Line:
                self.iface.messageBar().pushMessage(self.tr(u'Info'),
                                                     self.tr(u'Loaded layer {} does not have lineString type.')
                                                     .format(QFileInfo(fileName).baseName()),
                                                     level = QgsMessageBar.INFO, duration = 5)

    def onDirButton(self):
        """Get the destination file."""
        sender = '{}-lastUserFilePath'.format(self.sender().objectName())
        lastUsedFilePath = self.settings.value(sender, '')

        self.saveFileName = QFileDialog.getSaveFileName(self, self.tr(u'Select destination file'), 
                                                        self.tr(u'{}{}.csv').format(lastUsedFilePath,os.path.sep), 
                                                        filter ="CSV (*.csv)")
        self.save_file.setText(self.saveFileName)

        if self.saveFileName:
            self.settings.setValue(sender, os.path.dirname(self.saveFileName))

         # Enable the saveButton if file is chosen
        if not self.save_file.text():
            self.save_button.setEnabled(False)
        else:
            self.save_button.setEnabled(True)

    def onExportRasterValues(self):
        """Export sampled raster values to output CSV file.

        Prints error message when output file cannot be open for
        writing.

        Prints error when user selected length of segment is not positive real number
        and computation is not performed.

        When no raster or track vector layer given, than computation
        is not performed.
        """
        try:
            distanceBetweenVertices = float(self.vertex_dist.text().replace(',', '.'))
        except ValueError:
            self.iface.messageBar().pushMessage(self.tr(u'Error'),
                                                self.tr(u'{} is not a number.').format(self.vertex_dist.text()),
                                                level=QgsMessageBar.CRITICAL, duration = 5)
            return

        if distanceBetweenVertices <= 0:
            self.iface.messageBar().pushMessage(self.tr(u'Error'),
                                                self.tr(u'{} is not a positive number.').format(distanceBetweenVertices),
                                                level=QgsMessageBar.CRITICAL, duration = 5)
            return
        if not self.raster_box.currentLayer() or not self.track_box.currentLayer():
            self.iface.messageBar().pushMessage(self.tr(u'Error'),
                                                self.tr(u'No raster/track layer chosen.'),
                                                level=QgsMessageBar.CRITICAL, duration = 5)
            return

        # export values
        export = GroundRadiationMonitoringComputation().exportRasterValues(self.raster_box.currentLayer().id(),
                                                                           self.track_box.currentLayer().id(),
                                                                           self.saveFileName,
                                                                           self.vertex_dist.text())
        
        # check if export returns no error
        if not export:
            pass
        else:
            self.iface.messageBar().pushMessage(self.tr(u'Error'),
                                                self.tr(u'Unable open {} for writing. Reason: {}')
                                                .format(self.saveFileName, export),
                                                level=QgsMessageBar.CRITICAL, duration = 5)
            return

        self.iface.messageBar().pushMessage(self.tr(u'Info'),
                                            self.tr(u'File {} saved.').format(self.saveFileName),
                                            level=QgsMessageBar.INFO, duration = 5)