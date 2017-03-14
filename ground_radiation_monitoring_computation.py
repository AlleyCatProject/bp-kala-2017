# -*- coding: utf-8 -*-
import os

from PyQt4.QtCore import QSettings, QTranslator, qVersion, QCoreApplication, Qt, QFileInfo
from PyQt4.QtGui import QComboBox, QAction, QIcon, QToolButton, QFileDialog
from qgis.core import QgsMapLayerRegistry, QgsMapLayer, QGis, QgsPoint, QgsRaster, QgsProject,  QgsProviderRegistry, QgsDistanceArea
from qgis.utils import QgsMessageBar, iface
from qgis.gui import QgsMapLayerComboBox,QgsMapLayerProxyModel
from osgeo import gdal, ogr
from math import ceil
from array import array

from qgis.core import QgsVectorLayer, QgsField, QgsFeature, QgsGeometry, QgsVectorFileWriter
from PyQt4.QtCore import QVariant  

import osgeo.ogr as ogr
import osgeo.osr as osr
import csv

class GroundRadiationMonitoringComputation:
    def exportRasterValues(self, rasterLayerId, trackLayerId, fileName, vertexDist):
        """Export sampled raster values to output CSV file.

        :rasterLayerId: input raster layer (QgsRasterLayer)
        :trackLayerId: linestring vector layer to be sampled (QgsVectorLayer)
        :fileName: file descriptor of output CVS file
        :vertexDist: user defined distance between new vertices
        """
        try:
            csvFile = open(fileName, 'wb')
        except IOError as e:
            return e

        rasterLayer = QgsMapLayerRegistry.instance().mapLayer(rasterLayerId)
        trackLayer = QgsMapLayerRegistry.instance().mapLayer(trackLayerId)

        # get coordinates of vertices based on user defined sample segment length
        vectorX, vectorY = self.getCoor(rasterLayer, trackLayer, vertexDist)
        
        for X,Y in zip(vectorX,vectorY):
            value = rasterLayer.dataProvider().identify(QgsPoint(X,Y),QgsRaster.IdentifyFormatValue).results()
            csvFile.write('{val}{linesep}'.format(val=value.values()[0], linesep=os.linesep))

        # close output file
        csvFile.close()
        self.createShp(vectorX, vectorY, trackLayer, fileName)
        return None

    def getCoor(self, rasterLayer, trackLayer, vertexDist):
        """Get coordinates of vertices of sampled track.

        :rasterLayer: input raster layer (QgsRasterLayer)
        :trackLayer: linestring vector layer to be sampled (QgsVectorLayer)
        :vertexDist: user defined distance between new vertices
        """
        distanceBetweenVertices = float(vertexDist.replace(',', '.'))

        # declare arrays of coordinates of vertices
        vertexX = array('d',[])
        vertexY = array('d',[])

        # get coordinates of vertices of uploaded track layer
        for featureIndex, feature in enumerate(trackLayer.getFeatures()):
            polyline = feature.geometry().asPolyline()
            pointCounter = 0
            vertexX.append(polyline[0][0])
            vertexY.append(polyline[0][1])
            while pointCounter < (len(polyline)-1):
                point1 = polyline[pointCounter]
                point2 = polyline[pointCounter+1]
                distance = self.distance(point1,point2)

                # check whether the input distance between vertices is longer then the distance between points
                if distance > distanceBetweenVertices:
                    newX, newY = self.sampleLine(point1,point2, distance, distanceBetweenVertices)
                    vertexX.extend(newX)
                    vertexY.extend(newY)
                else:
                    vertexX.append(point2[0])
                    vertexY.append(point2[1])
                pointCounter = pointCounter + 1
 
        # returns coordinates of all vertices of track   
        return vertexX, vertexY        

    def distance(self, point1, point2):
        """Compute distance between points in metres.

        :point1: first point
        :point2: secound point
        """

        distance = QgsDistanceArea()
        distance.setEllipsoid('WGS84')
        distance.setEllipsoidalMode(True)
        d = distance.measureLine(QgsPoint(point1), QgsPoint(point2))
        return d

    def sampleLine(self,point1, point2, dist, distBetweenVertices):
        """Sample line between two points to segments of user selected length.

        Compute coordinates of new vertices.

        :point1: first point of line
        :point2: last point of line
        :dist: length of line in metres
        :distBetweenVertices: length of segment selected by user
        """

        # number of vertices, that should be added between 2 points
        vertexQuantity = ceil(dist / distBetweenVertices) - 1

        # if modulo of division of line length and 1 segment length is not 0,
        # point where last complete segment ends is computed
        if dist % distBetweenVertices != 0:
            shortestSegmentRel = (dist % distBetweenVertices) / dist
            lastPointX = point2[0] - (point2[0] - point1[0]) * shortestSegmentRel
            lastPointY = point2[1] - (point2[1] - point1[1]) * shortestSegmentRel
            vectorX = lastPointX - point1[0]
            vectorY = lastPointY - point1[1] 
        else:
            vectorX = point2[0] - point1[0]
            vectorY = point2[1] - point1[1]

        # compute addition to coordinates with size of 1 segment    
        addX = vectorX / vertexQuantity
        addY = vectorY / vertexQuantity

        # declare arrays for newly computed points
        newX = array('d',[])
        newY = array('d',[])

        # compute new points
        for n in range(1,int(vertexQuantity)):
            newX.append((point1[0]+n*addX))
            newY.append((point1[1]+n*addY))
        if lastPointX:
            newX.append(lastPointX)
            newY.append(lastPointY)
        newX.append(point2[0])
        newY.append(point2[1])

        return newX, newY

    def createShp(self, vectorX, vectorY, trackLayer, fileName):
        """Create ESRI shapefile and write new points. 

        :vectorX: X coordinates of points
        :vectorY: Y coordinates of points
        :trackLayer: layer to get coordinate system from
        :fileName: destination to save shapefile and coordinates of new points
        """
        shpFileName = '{}_shp.shp'.format(fileName.split('.')[0])
        coorFileName = '{}_coor.csv'.format(fileName.split('.')[0])

        # save csv with coordinates of new points
        csvFile = open('{f}'.format(f=coorFileName), 'wb')
        csvFile.write('X\tY{linesep}'.format(linesep=os.linesep))
        for X,Y in zip(vectorX,vectorY):
            csvFile.write('{X}\t{Y}{linesep}'.format(X=X, Y = Y,linesep=os.linesep))
        csvFile.close()

        reader = csv.DictReader(open('{f}'.format(f=coorFileName),"rb"),
                                delimiter='\t',
                                quoting=csv.QUOTE_NONE)

        # set up the shapefile driver
        driver = ogr.GetDriverByName("ESRI Shapefile")
        
        # create the data source
        data_source = driver.CreateDataSource('{f}'.format(f=shpFileName))

        # create the spatial reference
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(int(trackLayer.crs().authid()[5:]))

        # create the layer
        layer = data_source.CreateLayer("{}".format(fileName), srs, ogr.wkbPoint)

        # Add the fields we're interested in
        layer.CreateField(ogr.FieldDefn("X", ogr.OFTReal))
        layer.CreateField(ogr.FieldDefn("Y", ogr.OFTReal))

        # Process the text file and add the attributes and features to the shapefile
        for row in reader:
            # create the feature
            feature = ogr.Feature(layer.GetLayerDefn())
            # Set the attributes using the values from the delimited text file
            feature.SetField("X", row["X"])
            feature.SetField("Y", row["Y"])

            # create the WKT for the feature using Python string formatting
            wkt = "POINT(%f %f)" %  (float(row['X']) , float(row['Y']))

            # Create the point from the Well Known Txt
            point = ogr.CreateGeometryFromWkt(wkt)

            # Set the feature geometry using the point
            feature.SetGeometry(point)
            # Create the feature in the layer (shapefile)
            layer.CreateFeature(feature)
            # Dereference the feature
            feature = None

        # Save and close the data source
        data_source = None